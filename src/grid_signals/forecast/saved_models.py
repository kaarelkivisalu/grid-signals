"""Prepared SE3 wind models, checked reloads and explicit daily promotion."""

import hashlib
import json
import pickle  # noqa: S403 -- locally created artifacts, checked against recorded hashes
import platform
import shutil
import tempfile
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from grid_signals.forecast import config, paths, versions, windows
from grid_signals.forecast.evaluation.baselines import PhysicalPowerCurve
from grid_signals.forecast.features import assemble
from grid_signals.forecast.models.quantile import QuantileGBM
from grid_signals.forecast.storage import atomic_json, sync_directory, sync_file

ROOT = paths.DATA / "models/se3-wind"
POLICY = "se3-wind-saved-v1-daily-before-issue"


def utcnow() -> datetime:
    return datetime.now(UTC)


def settings() -> config.Config:
    cfg = config.load()
    cfg.task.resolution = "15min"
    cfg.features["temporal_method"] = "hourly_repeated"
    params = cfg.model.setdefault("quantile", {}).setdefault("params", {})
    params["n_jobs"] = 4
    return cfg


def environment() -> dict:
    packages = (
        "lightgbm",
        "numpy",
        "scikit-learn",
        "scipy",
        "pandas",
        "pyarrow",
        "pvlib",
        "windpowerlib",
        "scoringrules",
        "geopandas",
        "xarray",
        "netcdf4",
        "entsoe-py",
    )
    return {
        "python": platform.python_version(),
        **{name: version(name) for name in packages},
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(
    issue_day: date,
    *,
    root: Path | None = None,
    training: pd.DataFrame | None = None,
    cfg: config.Config | None = None,
) -> dict:
    """Fit off the prediction path, retain exact inputs and verify reload equivalence."""
    root = root or ROOT
    cfg = cfg or settings()
    code_sources = versions.sources()
    flags = assemble.run_flags(cfg.features.get("run_addressed", ()))
    if training is None:
        lag_targets = pd.read_parquet(
            paths.INTERIM / "targets_se3_wind_onshore.parquet"
        )[["period_start", "cf"]]
        training = assemble.require_run_coverage(
            assemble.build(**flags), cfg.features.get("run_addressed", ())
        )
    else:
        lag_targets = (
            training[["valid_time", "cf"]].rename(
                columns={"valid_time": "period_start"}
            )
            if "valid_time" in training
            else pd.DataFrame(
                {
                    "period_start": pd.to_datetime([], utc=True),
                    "cf": pd.Series([], dtype=float),
                }
            )
        )
    training_cutoff = min(issue_day, utcnow().date())
    training = training[training.delivery_day < pd.Timestamp(training_cutoff)].copy()
    if training.empty or training.delivery_day.nunique() < 60:
        raise ValueError(
            "model preparation needs at least 60 complete training days before issue"
        )
    if training.delivery_day.max() < pd.Timestamp(issue_day) - pd.Timedelta(days=3):
        raise ValueError("training actuals are more than three days behind the issue")
    levels = np.asarray(cfg.task.quantiles)
    if (
        cfg.task.zone != "SE3"
        or cfg.task.fuel_types != ["wind_onshore"]
        or not np.array_equal(levels, np.round(np.arange(0.05, 1, 0.05), 2))
    ):
        raise ValueError(
            "saved SE3 model policy requires onshore wind and the declared nineteen quantiles"
        )
    started = utcnow()
    model = QuantileGBM(levels, **cfg.model.get("quantile", {})).fit(training)
    reference = PhysicalPowerCurve(levels).fit(training)
    probe = training.tail(96).copy()
    expected = model.predict(probe)
    baseline_expected = reference.predict(probe)
    if code_sources != versions.sources():
        raise RuntimeError("code/settings changed during model preparation")
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=root))
    try:
        training.to_parquet(temporary / "training.parquet", index=False)
        lag_targets.to_parquet(temporary / "lag_targets.parquet", index=False)
        probe.to_parquet(temporary / "reload_inputs.parquet", index=False)
        np.savez(
            temporary / "reload_predictions.npz",
            model=expected,
            reference=baseline_expected,
        )
        with (temporary / "model.pkl").open("wb") as handle:
            pickle.dump({"model": model, "reference": reference}, handle, protocol=5)
        with (temporary / "model.pkl").open("rb") as handle:
            restored = pickle.load(handle)  # noqa: S301 -- our just-written artifact
        for name, predictions in (
            ("model", expected),
            ("reference", baseline_expected),
        ):
            np.testing.assert_allclose(
                restored[name].predict(probe), predictions, rtol=1e-12, atol=1e-12
            )
        record = {
            "schema_version": 1,
            "policy": POLICY,
            "issue_day": issue_day.isoformat(),
            "training_cutoff_exclusive": training_cutoff.isoformat(),
            "training_max_day": str(training.delivery_day.max().date()),
            "training_days": int(training.delivery_day.nunique()),
            "training_rows": len(training),
            "fit_started_at": started.isoformat(),
            "prepared_at": utcnow().isoformat(),
            "config": cfg.model_dump(mode="json"),
            "config_sha256": cfg.fingerprint(),
            "code_sources": code_sources,
            "environment": environment(),
            "files": {p.name: digest(p) for p in temporary.iterdir()},
            "reload_verified": True,
            "validation": "Fixed-input reload equivalence; not a new evaluation of forecast skill.",
        }
        record["model_id"] = (
            POLICY
            + "+"
            + hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[
                :20
            ]
        )
        (temporary / "record.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        destination = root / record["model_id"]
        for file in temporary.iterdir():
            sync_file(file)
        sync_directory(temporary)
        temporary.rename(destination)
        sync_directory(root)
        return record
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def validate(
    model_id: str,
    issue_day: date,
    *,
    root: Path | None = None,
    current_time: datetime | None = None,
) -> tuple[dict, dict]:
    root = root or ROOT
    if Path(model_id).name != model_id:
        raise ValueError("invalid saved model identity")
    directory = root / model_id
    record = json.loads((directory / "record.json").read_text())
    if (
        record["model_id"] != model_id
        or record["policy"] != POLICY
        or record["issue_day"] != issue_day.isoformat()
    ):
        raise ValueError(
            "saved model does not match the requested issue and preparation policy"
        )
    now = current_time or utcnow()
    prepared = datetime.fromisoformat(record["prepared_at"])
    if not timedelta(0) <= now - prepared <= timedelta(hours=30):
        raise ValueError("saved model is stale or prepared in the future")
    if (
        record["code_sources"] != versions.sources()
        or record["environment"] != environment()
    ):
        raise ValueError(
            "saved model code/settings or dependency versions differ from the runner"
        )
    if (
        date.fromisoformat(record["training_cutoff_exclusive"]) > issue_day
        or date.fromisoformat(record["training_max_day"])
        >= date.fromisoformat(record["training_cutoff_exclusive"])
        or prepared > windows.issue_time(issue_day)
    ):
        raise ValueError("saved training cutoff crosses the issue boundary")
    if not record["reload_verified"]:
        raise ValueError("saved model has not passed reload verification")
    for filename, checksum in record["files"].items():
        if Path(filename).name != filename or digest(directory / filename) != checksum:
            raise ValueError("saved model or retained inputs have a checksum mismatch")
    with (directory / "model.pkl").open("rb") as handle:
        models = pickle.load(handle)  # noqa: S301 -- trusted local model verified before deserializing
    return models, record


def promote(
    model_id: str, issue_day: date, *, reason: str, root: Path | None = None
) -> dict:
    root = root or ROOT
    if not reason.strip():
        raise ValueError("promotion needs an explicit reason")
    _, record = validate(model_id, issue_day, root=root)
    pointer = {
        "model_id": model_id,
        "issue_day": issue_day.isoformat(),
        "record_sha256": digest(root / model_id / "record.json"),
        "promoted_at": utcnow().isoformat(),
        "reason": reason,
    }
    history = root / "promotions"
    history.mkdir(exist_ok=True)
    atomic_json(history / f"{uuid4()}.json", pointer)
    atomic_json(root / "active.json", pointer)
    return record


def load(issue_day: date, *, root: Path | None = None) -> tuple[dict, dict]:
    root = root or ROOT
    pointer = json.loads((root / "active.json").read_text())
    model_id = pointer["model_id"]
    if (
        Path(model_id).name != model_id
        or digest(root / model_id / "record.json") != pointer["record_sha256"]
    ):
        raise ValueError("promoted model version record changed")
    return validate(model_id, issue_day, root=root)
