"""SE3 saved-model predictions and one atomic public result generation.

Immutable candidate files keep model inputs and forecasts. The public pointer is
also the delivery receipt: only a committed issue can enter forward scoring.
"""

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from operator import itemgetter
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from grid_signals.forecast import journal, paths, publication, saved_models, windows
from grid_signals.forecast.evaluation import metrics
from grid_signals.forecast.features import assemble
from grid_signals.forecast.reporting.export_explorer import DISPLAY_LEVELS
from grid_signals.forecast.sources import entsoe
from grid_signals.forecast.storage import atomic_json, sync_directory, sync_file
from grid_signals.forecast.targets import actuals

ROOT = paths.DATA / "runtime/se3-wind"
PUBLIC = paths.OUTPUT


def utcnow() -> datetime:
    return datetime.now(UTC)


@contextmanager
def lock(root: Path | None = None):
    root = root or ROOT
    root.mkdir(parents=True, exist_ok=True)
    with (root / "operation.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def initialize(first_issue_day: date, *, root: Path | None = None) -> dict:
    root = root or ROOT
    root.mkdir(parents=True, exist_ok=True)
    path = root / "trial.json"
    if path.exists():
        return json.loads(path.read_text())
    value = {
        "first_issue_day": first_issue_day.isoformat(),
        "activated_at": utcnow().isoformat(),
        "policy": saved_models.POLICY,
    }
    atomic_json(path, value)
    sync_directory(root.parent)
    return value


def current(public: Path | None = None) -> dict:
    public = public or PUBLIC
    path = public / "current.json"
    if not path.exists():
        return {"deliveries": {}, "schema_version": 1}
    pointer = json.loads(path.read_text())
    generation = pointer["generation"]
    if Path(generation).name != generation:
        raise ValueError("unsafe public generation")
    index = public / "generations" / generation / "files.json"
    if saved_models.digest(index) != pointer["index_sha256"]:
        raise ValueError("public result index checksum mismatch")
    for name, checksum in json.loads(index.read_text()).items():
        file = index.parent / name
        if (
            not file.resolve().is_relative_to(index.parent.resolve())
            or saved_models.digest(file) != checksum
        ):
            raise ValueError("public result payload checksum mismatch")
    return pointer


def candidate(issue_day: date, *, root: Path | None = None) -> dict:
    """Prediction only: no fitting and no fallback to a different trained model."""
    root = root or ROOT
    models, record = saved_models.load(issue_day)
    cfg = saved_models.config.Config.model_validate(record["config"])
    flags = assemble.run_flags(cfg.features.get("run_addressed", ()))
    delivery = issue_day + timedelta(days=1)
    started = utcnow()
    lag_targets = pd.read_parquet(
        saved_models.ROOT / record["model_id"] / "lag_targets.parquet"
    )
    history = pd.Series(
        lag_targets.cf.to_numpy(),
        index=pd.to_datetime(lag_targets.period_start, utc=True),
    )
    future = assemble.build_operational(
        delivery,
        "SE3",
        "wind_onshore",
        resolution="1h",
        actual_history=history,
        **flags,
    )
    required = [
        "power_curve_model_mean",
        *[assemble.RUN_SOURCES[name] for name in cfg.features.get("run_addressed", ())],
    ]
    expected = pd.DatetimeIndex(windows.delivery_day_starts(delivery))
    if (
        not pd.DatetimeIndex(future.valid_time).equals(expected)
        or future[required].isna().any().any()
    ):
        raise ValueError("incomplete hourly weather for the delivery day")
    provenance = assemble.max_source_time(future)
    if (provenance.max(axis=1) > pd.Timestamp(windows.issue_time(issue_day))).any():
        raise ValueError("forecast inputs cross the information cutoff")
    values = {name: model.predict(future) for name, model in models.items()}
    grid = pd.DatetimeIndex(
        windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
    )
    positions = pd.DatetimeIndex(future.valid_time).get_indexer(grid.floor("h"))
    frame = future.iloc[positions][["capacity_mw"]].reset_index(drop=True)
    frame["valid_time"], frame["delivery_day"] = grid, pd.Timestamp(delivery)
    frame["period_end"] = grid + pd.Timedelta(minutes=15)
    frame["zone"], frame["fuel_type"], frame["resolution"] = (
        "SE3",
        "wind_onshore",
        "15min",
    )
    frame["temporal_method"], frame["daylight"] = "hourly_repeated", True
    frame["issue_time"] = windows.issue_time(issue_day)
    frame["model_version"], frame["saved_model_id"] = (
        record["model_id"],
        record["model_id"],
    )
    frame["training_cutoff_exclusive"] = record["training_cutoff_exclusive"]
    frame["training_max_day"] = record["training_max_day"]
    frame["model_prepared_at"] = record["prepared_at"]
    frame["created_at"], frame["run_started_at"] = utcnow(), started
    forecast_id = str(uuid4())
    frame["forecast_id"] = forecast_id
    frame["information_cutoff_at"] = windows.issue_time(issue_day)
    frame["publication_deadline_at"] = (
        windows.issue_time(issue_day) + publication.DEADLINE_SLACK
    )
    for name, quantiles in values.items():
        if not np.isfinite(frame.capacity_mw).all() or (frame.capacity_mw <= 0).any():
            raise ValueError("capacity must be finite and positive")
        if (
            quantiles.shape != (len(future), len(cfg.task.quantiles))
            or not np.isfinite(quantiles).all()
            or (np.diff(quantiles, axis=1) < 0).any()
        ):
            raise ValueError("non-finite, incomplete or crossing saved-model forecast")
        prefix = "" if name == "model" else "reference_"
        for level, column in zip(cfg.task.quantiles, quantiles.T, strict=True):
            frame[f"{prefix}cf_q{level:.2f}"] = column[positions]
            frame[f"{prefix}mw_q{level:.2f}"] = column[positions] * frame.capacity_mw
    directory = root / "issues" / forecast_id
    directory.mkdir(parents=True, exist_ok=False)
    future.to_parquet(directory / "inputs.parquet", index=False)
    frame.to_parquet(directory / "forecast.parquet", index=False)
    payload = {
        "forecast_id": forecast_id,
        "issue_day": issue_day.isoformat(),
        "delivery_day": delivery.isoformat(),
        "saved_model_id": record["model_id"],
        "forecast_sha256": saved_models.digest(directory / "forecast.parquet"),
        "inputs_sha256": saved_models.digest(directory / "inputs.parquet"),
    }
    sync_file(directory / "inputs.parquet")
    sync_file(directory / "forecast.parquet")
    atomic_json(directory / "record.json", payload)
    sync_directory(directory.parent)
    sync_directory(root)
    return payload


def read_issue(forecast_id: str, *, root: Path | None = None) -> pd.DataFrame:
    root = root or ROOT
    if Path(forecast_id).name != forecast_id:
        raise ValueError("invalid forecast identity")
    directory = root / "issues" / forecast_id
    record = json.loads((directory / "record.json").read_text())
    for name, key in (
        ("forecast.parquet", "forecast_sha256"),
        ("inputs.parquet", "inputs_sha256"),
    ):
        if saved_models.digest(directory / name) != record[key]:
            raise ValueError("immutable issue file changed")
    return pd.read_parquet(directory / "forecast.parquet")


def eligible_receipts(pointer: dict) -> dict[str, dict]:
    selected = {}
    for forecast_id, receipt in sorted(
        pointer.get("deliveries", {}).items(),
        key=lambda item: item[1].get("published_at") or "",
    ):
        if receipt["publication_status"] == "on_time":
            selected.setdefault(
                receipt["issue_day"], {**receipt, "forecast_id": forecast_id}
            )
    return selected


def score(frame: pd.DataFrame, observed: pd.DataFrame) -> dict | None:
    if observed.empty:
        return None
    delivery = pd.Timestamp(frame.delivery_day.iloc[0]).date()
    expected = pd.DatetimeIndex(
        windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
    )
    if not pd.DatetimeIndex(frame.valid_time).equals(expected):
        return None
    joined = frame.merge(
        observed[["period_start", "mw"]],
        left_on="valid_time",
        right_on="period_start",
        how="left",
        validate="one_to_one",
    )
    if len(joined) != len(expected) or not np.isfinite(joined.mw).all():
        return None
    levels = np.round(np.arange(0.05, 1, 0.05), 2)
    result = {}
    actual = (joined.mw / joined.capacity_mw).to_numpy()
    for name, prefix in (("model", ""), ("physical_reference", "reference_")):
        result[name] = {
            **metrics.summarise(
                actual,
                joined[[f"{prefix}cf_q{level:.2f}" for level in levels]].to_numpy(),
                levels,
            ),
            "mae_mw": float((joined[f"{prefix}mw_q0.50"] - joined.mw).abs().mean()),
        }
    result["scored_intervals"] = len(joined)
    result["crps_skill_vs_physical"] = metrics.skill_score(
        result["model"]["crps"], result["physical_reference"]["crps"]
    )
    return result


def captured_curve(
    capture: dict, grid: pd.DatetimeIndex
) -> tuple[pd.Series, str] | None:
    identity = capture["capture_id"]
    if Path(identity).name != identity or identity in {".", ".."}:
        return None
    raw = journal.ROOT / "raw_captures" / f"{identity}.xml"
    parsed = raw.with_suffix(".parquet")
    if (
        not raw.exists()
        or saved_models.digest(raw) != capture["sha256"]
        or not parsed.exists()
    ):
        return None
    if (
        capture.get("parsed_sha256")
        and saved_models.digest(parsed) != capture["parsed_sha256"]
    ):
        return None
    values = pd.read_parquet(parsed)
    selected = (
        values.fuel_type.astype(str).str.lower().str.replace(" ", "").eq("windonshore")
    )
    values = values[selected]
    if values.period_start.duplicated().any():
        return None
    values = values.set_index("period_start").forecast_mw.sort_index()
    source_resolution = "15min"
    if not values.index.equals(grid):
        hourly = pd.DatetimeIndex(grid.floor("h").unique())
        if not values.index.equals(hourly):
            return None
        values = pd.Series(values.reindex(grid.floor("h")).to_numpy(), index=grid)
        source_resolution = "hourly repeated"
    return (values, source_resolution) if np.isfinite(values).all() else None


def public_comparison(
    frame: pd.DataFrame, observed: pd.DataFrame, captures: list[dict]
) -> dict | None:
    if observed.empty:
        return None
    delivery = pd.Timestamp(frame.delivery_day.iloc[0]).date().isoformat()
    candidates = [
        row
        for row in captures
        if row.get("zone") == "SE3"
        and row.get("target") == "wind_solar"
        and row.get("delivery_day") == delivery
        and row.get("status") == "captured"
        and row.get("eligible_at_cutoff")
    ]
    grid = pd.DatetimeIndex(frame.valid_time)
    for capture in sorted(candidates, key=itemgetter("received_at")):
        curve = captured_curve(capture, grid)
        if curve is None:
            continue
        values, source_resolution = curve
        actual = observed.set_index("period_start").mw.reindex(grid)
        if not np.isfinite(actual).all():
            continue
        return {
            "capture_id": capture["capture_id"],
            "received_at": capture["received_at"],
            "sha256": capture["sha256"],
            "source_resolution": source_resolution,
            "scored_intervals": len(grid),
            "mae_mw": float((values - actual).abs().mean()),
            "nmae": float(
                (
                    (values - actual).abs().to_numpy() / frame.capacity_mw.to_numpy()
                ).mean()
            ),
        }
    return None


def active_model_status() -> dict:
    try:
        pointer = json.loads((saved_models.ROOT / "active.json").read_text())
        _, record = saved_models.load(date.fromisoformat(pointer["issue_day"]))
    except (OSError, ValueError, KeyError) as error:
        return {"status": "unavailable", "error_type": type(error).__name__}
    return {
        "status": "ready",
        **{
            key: record[key]
            for key in (
                "model_id",
                "issue_day",
                "prepared_at",
                "training_cutoff_exclusive",
                "training_max_day",
                "training_days",
                "reload_verified",
            )
        },
    }


def status_record(
    pointer: dict,
    *,
    root: Path | None = None,
    observed: pd.DataFrame | None = None,
    now: datetime | None = None,
) -> dict:
    root = root or ROOT
    now = now or utcnow()
    trial = root / "trial.json"
    if not trial.exists():
        return {
            "status": "not_started",
            "issues": [],
            "generated_at": now.isoformat(),
            "reliability_gate": {
                "required_consecutive_issues": 30,
                "consecutive_on_time": 0,
                "met": False,
            },
        }
    start = date.fromisoformat(json.loads(trial.read_text())["first_issue_day"])
    if observed is None:
        raw = entsoe.load("actual_generation", "SE3")
        observed = (
            actuals.to_quarter_hourly(raw)
            if not raw.empty
            else pd.DataFrame(columns=["period_start", "mw", "fuel_type"])
        )
        observed = observed[observed.fuel_type == "wind_onshore"]
    eligible = eligible_receipts(pointer)
    attempts = journal.read("lifecycle", root)
    captures = journal.read("captures")
    issues = []
    for timestamp in pd.date_range(start, now.date(), freq="D"):
        issue = timestamp.date()
        cutoff = windows.issue_time(issue)
        matching = [row for row in attempts if row["issue_day"] == issue.isoformat()]
        receipt = eligible.get(issue.isoformat())
        entry = {
            "issue_day": issue.isoformat(),
            "delivery_day": (issue + timedelta(days=1)).isoformat(),
            "deadline_at": (cutoff + publication.DEADLINE_SLACK).isoformat(),
            "status": "missing"
            if now > cutoff + publication.DEADLINE_SLACK
            else "pending",
            "forecast_id": None,
            "published_at": None,
            "saved_model_id": None,
            "score": None,
            "jobs": {},
        }
        for row in sorted(
            matching, key=lambda row: (row["at"], row.get("recorded_at_ns", 0))
        ):
            entry["jobs"][row["operation"]] = {
                key: row[key]
                for key in ("status", "at", "error_type", "elapsed_seconds")
                if key in row
            }
        if receipt is None:
            delivered = [
                dict(value, forecast_id=key)
                for key, value in pointer.get("deliveries", {}).items()
                if value["issue_day"] == issue.isoformat()
            ]
            receipt = (
                max(delivered, key=lambda value: value.get("published_at") or "")
                if delivered
                else None
            )
        for operation, job in entry["jobs"].items():
            budget = 3000 if operation in {"prepare", "backup"} else 1200
            if (
                job["status"] == "running"
                and (now - datetime.fromisoformat(job["at"])).total_seconds() > budget
            ):
                job["status"] = "interrupted"
        entry["collection"] = [
            {
                key: capture[key]
                for key in (
                    "capture_id",
                    "status",
                    "received_at",
                    "eligible_at_cutoff",
                    "sha256",
                    "error_type",
                    "source",
                    "process_type",
                    "document",
                )
                if key in capture
            }
            for capture in captures
            if capture.get("zone") == "SE3"
            and capture.get("delivery_day") == entry["delivery_day"]
        ]
        if receipt:
            entry.update(
                {
                    key: receipt[key]
                    for key in (
                        "forecast_id",
                        "published_at",
                        "saved_model_id",
                        "publication_status",
                    )
                }
            )
            entry["status"] = entry.pop("publication_status")
            entry.update(
                {
                    key: receipt.get(key)
                    for key in (
                        "training_cutoff_exclusive",
                        "training_max_day",
                        "model_prepared_at",
                    )
                }
            )
            if issue.isoformat() in eligible:
                forecast = read_issue(receipt["forecast_id"], root=root)
                entry["score"] = score(forecast, observed)
                if entry["score"] is not None:
                    entry["score"]["public_reference"] = public_comparison(
                        forecast, observed, captures
                    )
        elif entry["jobs"].get("forecast", {}).get("status") == "failed":
            entry["status"] = "failed"
        elif (
            entry["jobs"].get("forecast", {}).get("status")
            in {"running", "interrupted"}
            and now > cutoff + publication.DEADLINE_SLACK
        ):
            entry["status"] = "interrupted"
        issues.append(entry)
    consecutive = 0
    for row in reversed(
        [row for row in issues if datetime.fromisoformat(row["deadline_at"]) < now]
    ):
        if row["status"] != "on_time":
            break
        consecutive += 1
    return {
        "status": "running",
        "product": "se3-wind",
        "generated_at": now.isoformat(),
        "first_issue_day": start.isoformat(),
        "active_model": active_model_status(),
        "issues": issues,
        "reliability_gate": {
            "required_consecutive_issues": 30,
            "consecutive_on_time": consecutive,
            "met": consecutive >= 30,
        },
        "scores_provisional": True,
    }


def public_rows(pointer: dict, *, root: Path | None = None) -> pd.DataFrame:
    root = root or ROOT
    parts = []
    for forecast_id, receipt in pointer.get("deliveries", {}).items():
        frame = read_issue(forecast_id, root=root)
        for model, prefix in (
            ("hourly_repeated", ""),
            ("physical_power_curve", "reference_"),
        ):
            rows = frame[
                ["valid_time", "forecast_id", "model_version", "capacity_mw"]
            ].copy()
            rows["delivery_date"] = pd.to_datetime(frame.delivery_day).dt.strftime(
                "%Y-%m-%d"
            )
            rows["target"], rows["model"], rows["split"] = (
                "wind_onshore",
                model,
                "Published archive",
            )
            rows["actual"], rows["eligible"] = np.nan, False
            for level in DISPLAY_LEVELS:
                rows[f"q{level:.2f}"] = frame[f"{prefix}mw_q{level:.2f}"]
            rows["published_at"] = pd.to_datetime(
                pd.Series(receipt["published_at"], index=rows.index), utc=True
            )
            rows["information_cutoff_at"] = frame.information_cutoff_at
            rows["publication_status"] = receipt["publication_status"]
            parts.append(rows)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copyfile(source, destination)


def acknowledge(pointer: dict, forecast_id: str, *, root: Path, public: Path) -> dict:
    """Acknowledge only after the complete generation is already publicly visible.

    A crash before acknowledgement stays unverified. Recovery records its real
    acknowledgement time, rather than inventing an earlier on-time receipt.
    """
    rows = read_issue(forecast_id, root=root)
    acknowledged = utcnow()
    receipt = pointer["deliveries"][forecast_id]
    receipt["published_at"] = acknowledged.isoformat()
    receipt["publication_status"] = publication.status(
        pd.Timestamp(rows.issue_time.iloc[0]).to_pydatetime(),
        pd.Timestamp(rows.run_started_at.iloc[0]).to_pydatetime(),
        acknowledged,
    )
    pointer["committed_at"] = acknowledged.isoformat()
    atomic_json(public / "current.json", pointer)
    return pointer


def publish(
    forecast_id: str | None = None,
    *,
    root: Path | None = None,
    public: Path | None = None,
    observed: pd.DataFrame | None = None,
) -> dict:
    """Switch a complete generation once; that pointer is the delivery evidence."""
    root = root or ROOT
    public = public or PUBLIC
    pointer = current(public)
    # Idempotent retries never change an existing public forecast's receipt.
    if forecast_id in pointer.get("deliveries", {}):
        if (
            pointer["deliveries"][forecast_id]["publication_status"]
            == "pending_delivery"
        ):
            return acknowledge(pointer, forecast_id, root=root, public=public)
        return pointer
    generation = str(uuid4())
    parent = public / "generations"
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".building-", dir=parent))
    try:
        seed = (
            (public / "generations" / pointer["generation"])
            if "generation" in pointer
            else Path(__file__).parents[1] / "app/assets"
        )
        explorer = stage / "explorer"
        explorer.mkdir()
        index = json.loads((seed / "explorer/manifest.json").read_text())
        names = {
            info[key]
            for info in index["zones"].values()
            for key in (
                "forecast_file",
                "observation_file",
                "live_forecast_file",
                "live_observation_file",
            )
            if info.get(key)
        }
        for name in names:
            if Path(name).name != name:
                raise ValueError("unsafe exported filename")
            link_or_copy(seed / "explorer" / name, explorer / name)
        shutil.copyfile(
            seed / "explorer/market-areas.geojson", explorer / "market-areas.geojson"
        )
        for name in (
            "forecast_snapshot.json",
            "price_snapshot.json",
            "load_snapshot.json",
        ):
            link_or_copy(seed / name, stage / name)
        next_pointer = {
            "schema_version": 1,
            "generation": generation,
            "deliveries": dict(pointer.get("deliveries", {})),
        }
        if forecast_id is not None:
            rows = read_issue(forecast_id, root=root)
            cutoff = pd.Timestamp(rows.issue_time.iloc[0]).to_pydatetime()
            next_pointer["deliveries"][forecast_id] = {
                "issue_day": cutoff.date().isoformat(),
                "saved_model_id": rows.saved_model_id.iloc[0],
                "training_cutoff_exclusive": rows.training_cutoff_exclusive.iloc[0],
                "training_max_day": rows.training_max_day.iloc[0],
                "model_prepared_at": rows.model_prepared_at.iloc[0],
                "published_at": None,
                "publication_status": "pending_delivery",
            }

        def artifact(frame: pd.DataFrame, name: str) -> str:
            raw = frame.to_parquet(index=False, compression="zstd")
            filename = f"SE3-{name}-{hashlib.sha256(raw).hexdigest()[:16]}.parquet"
            if not (explorer / filename).exists():
                (explorer / filename).write_bytes(raw)
            return filename

        live = public_rows(next_pointer, root=root)
        info = index["zones"]["SE3"]
        if not live.empty:
            info["live_forecast_file"] = artifact(live, "live-forecasts")
            info["dates"] = sorted(set(info["dates"]) | set(live.delivery_date))
            index["zones"]["SE3"]["dates"] = info["dates"]
        if observed is None:
            raw = entsoe.load("actual_generation", "SE3")
            observed = (
                actuals.to_quarter_hourly(raw)
                if not raw.empty
                else pd.DataFrame(columns=["period_start", "mw", "fuel_type"])
            )
            observed = observed[observed.fuel_type == "wind_onshore"]
        if not observed.empty:
            observed = observed[["period_start", "mw"]].rename(
                columns={"period_start": "valid_time", "mw": "wind_onshore"}
            )
            info["live_observation_file"] = artifact(observed, "live-observations")
        # status_record needs target-form observations, independently of explorer names.
        score_observed = observed.rename(
            columns={"valid_time": "period_start", "wind_onshore": "mw"}
        )
        record = status_record(next_pointer, root=root, observed=score_observed)
        atomic_json(stage / "publication.json", record)
        index["exported_at"] = utcnow().isoformat()
        atomic_json(explorer / "manifest.json", index)
        # Keep only files referenced by this generation; old generations remain immutable.
        keep = {
            value[key]
            for value in index["zones"].values()
            for key in (
                "forecast_file",
                "observation_file",
                "live_forecast_file",
                "live_observation_file",
            )
            if value.get(key)
        } | {"manifest.json", "market-areas.geojson"}
        for file in explorer.iterdir():
            if file.name not in keep:
                file.unlink()
        file_index = {
            str(file.relative_to(stage)): saved_models.digest(file)
            for file in stage.rglob("*")
            if file.is_file()
        }
        atomic_json(stage / "files.json", file_index)
        next_pointer["index_sha256"] = saved_models.digest(stage / "files.json")
        next_pointer["committed_at"] = utcnow().isoformat()
        for file in stage.rglob("*"):
            if file.is_file():
                sync_file(file)
        sync_directory(explorer)
        sync_directory(stage)
        stage.rename(parent / generation)
        sync_directory(parent)
        if "generation" in pointer:
            atomic_json(public / "previous.json", pointer)
        atomic_json(public / "current.json", next_pointer)
        for identity, receipt in next_pointer["deliveries"].items():
            if receipt["publication_status"] == "pending_delivery":
                acknowledge(next_pointer, identity, root=root, public=public)
        return next_pointer
    finally:
        if stage.exists():
            shutil.rmtree(stage)
