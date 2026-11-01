"""Portable market data and interval-weighted diagnostics; no research dependencies."""

import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from grid_signals.app import results
from grid_signals.app.snapshot import SnapshotError

DEFAULT_ROOT = Path(__file__).parent / "assets/explorer"
SCORED_SPLITS = ("Final holdout", "Development")
GROUPS = ("Overall", "Year", "Season", "Month", "Weekday", "Market quarter")


def bundle_root() -> Path:
    return Path(
        os.environ.get("GRID_SIGNALS_EXPLORER_PATH", results.selected()[0] / "explorer")
    )


def load_manifest() -> dict:
    try:
        root, pointer, error = results.selected()
        explorer = Path(os.environ.get("GRID_SIGNALS_EXPLORER_PATH", root / "explorer"))
        payload = json.loads((explorer / "manifest.json").read_text())
        payload["_root"] = str(explorer)
        payload["_deliveries"] = pointer.get("deliveries", {})
        payload["_publication"] = results.publication_record(root, pointer)
        payload["_result_error"] = error
        if payload["schema_version"] != 1 or not payload["zones"]:
            raise ValueError  # noqa: TRY301
        for info in payload["zones"].values():
            for key in (
                "forecast_file",
                "observation_file",
                "live_forecast_file",
                "live_observation_file",
            ):
                name = info.get(key)
                if name and (Path(name).name != name or not name.endswith(".parquet")):
                    raise ValueError  # noqa: TRY301
    except (OSError, KeyError, TypeError, ValueError) as exc:
        message = "The market explorer bundle is missing or incompatible."
        raise SnapshotError(message) from exc
    else:
        return payload


@st.cache_data(show_spinner=False, max_entries=16)
def _read_artifact(
    _root: str,
    filename: str,
    kind: str,
    cache_id: str = "",  # noqa: ARG001 -- part of the Streamlit cache key
) -> pd.DataFrame:
    frame = pd.read_parquet(Path(_root) / filename)
    required = {"valid_time"}
    if kind == "forecast":
        required.update(
            {
                "model",
                "target",
                "delivery_date",
                "split",
                "actual",
                "eligible",
                *[
                    f"q{level}"
                    for level in (
                        "0.05",
                        "0.10",
                        "0.25",
                        "0.50",
                        "0.75",
                        "0.90",
                        "0.95",
                    )
                ],
            }
        )
    if not required.issubset(frame.columns) or not isinstance(
        frame.valid_time.dtype, pd.DatetimeTZDtype
    ):
        message = "Invalid exported series schema."
        raise ValueError(message)
    return frame


def read_market(manifest: dict, zone: str, kind: str) -> pd.DataFrame:
    info = manifest["zones"].get(zone, {})
    names = [info.get(f"{kind}_file"), info.get(f"live_{kind}_file")]
    root = str(manifest.get("_root") or bundle_root())
    try:
        parts = [
            _read_artifact(
                root,
                name,
                kind,
                cache_id="" if re.search(r"-[0-9a-f]{16}\.parquet$", name) else root,
            )
            for name in names
            if name
        ]
        if not parts:
            return pd.DataFrame()
        frame = (
            pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0].copy()
        )
        if kind == "observation":
            # A fresh wind-only actual must not erase other products at that instant.
            frame = frame.groupby("valid_time", as_index=False).last()
        elif "forecast_id" in frame:
            for forecast_id, receipt in manifest.get("_deliveries", {}).items():
                selected = frame.forecast_id == forecast_id
                frame.loc[selected, "published_at"] = pd.Timestamp(
                    receipt["published_at"]
                )
                frame.loc[selected, "publication_status"] = receipt[
                    "publication_status"
                ]
                for field in (
                    "saved_model_id",
                    "training_cutoff_exclusive",
                    "training_max_day",
                    "model_prepared_at",
                ):
                    if field not in frame:
                        frame[field] = pd.Series(None, index=frame.index, dtype=object)
                    frame.loc[selected, field] = receipt.get(field)
    except (OSError, ValueError) as exc:
        message = "This market's exported data is unavailable."
        raise SnapshotError(message) from exc
    else:
        return frame


def suggested_backtest_day(info: dict) -> str | None:
    """Latest shared final (then development) date, across evaluated targets."""
    targets = list(info.get("targets", {}).values())
    for split in SCORED_SPLITS:
        dates = [
            set(target.get("dates_by_split", {}).get(split, [])) for target in targets
        ]
        if dates:
            common = set.intersection(*dates)
            if common:
                return max(common)
    return None


def local_dates(times: pd.Series, timezone: str) -> pd.Series:
    return (
        pd.to_datetime(times, utc=True).dt.tz_convert(timezone).dt.strftime("%Y-%m-%d")
    )


def market_quarters(times: pd.Series, timezone: str) -> pd.Series:
    """Ordinal interval since local midnight; retain both autumn repeated hours."""
    local = pd.to_datetime(times, utc=True).dt.tz_convert(timezone)
    return ((local - local.dt.normalize()).dt.total_seconds() // 900 + 1).astype(int)


def group_labels(frame: pd.DataFrame, group: str, timezone: str) -> pd.Series:
    local = pd.to_datetime(frame.valid_time, utc=True).dt.tz_convert(timezone)
    if group == "Year":
        return local.dt.strftime("%Y")
    if group == "Month":
        return local.dt.strftime("%Y-%m")
    if group == "Weekday":
        return local.dt.dayofweek.map(
            dict(
                enumerate(
                    ["1 Mon", "2 Tue", "3 Wed", "4 Thu", "5 Fri", "6 Sat", "7 Sun"]
                )
            )
        )
    if group == "Season":
        season = ((local.dt.month % 12) // 3).map(
            {0: "1 Winter", 1: "2 Spring", 2: "3 Summer", 3: "4 Autumn"}
        )
        year = local.dt.year + (local.dt.month == 12).astype(int)
        return year.astype(str) + " · " + season
    if group == "Market quarter":
        return market_quarters(frame.valid_time, timezone).map(
            lambda value: f"Q{value:03d}"
        )
    return pd.Series("All intervals", index=frame.index)


def matched_rows(frame: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Compare selected models on identical eligible split/timestamp observations."""
    rows = frame[frame.model.isin(models) & frame.eligible.eq(other=True)].copy()
    if rows.empty:
        return rows
    keys = ["split", "valid_time"]
    if rows.duplicated([*keys, "model"]).any():
        message = "Duplicate model intervals cannot be compared."
        raise ValueError(message)
    counts = rows.groupby(keys).model.transform("nunique")
    rows = rows[counts == len(models)]
    # Models must have been scored against the same target, not just the same clock.
    targets = rows.groupby(keys).actual
    differing = targets.transform("max") - targets.transform("min")
    if (differing > 1e-5).any():
        message = "Models use different scoring targets on matched intervals."
        raise ValueError(message)
    return rows


def grouped_scores(
    frame: pd.DataFrame, group: str, timezone: str, *, capacity: bool = False
) -> pd.DataFrame:
    """Aggregate per-interval losses; never average already aggregated daily metrics."""
    if frame.empty:
        return pd.DataFrame()
    rows = frame.copy()
    rows["Group"] = group_labels(rows, group, timezone)
    suffix = "_capacity" if capacity else ""
    result = (
        rows.groupby(["split", "model", "Group"], sort=True)
        .agg(
            MAE=(f"mae{suffix}", "mean"),
            CRPS=(f"crps{suffix}", "mean"),
            Bias=(f"bias{suffix}", "mean"),
            Coverage80=("coverage_80", "mean"),
            Coverage90=("coverage_90", "mean"),
            Days=("delivery_date", "nunique"),
            Intervals=("valid_time", "size"),
        )
        .reset_index()
    )
    result[["Coverage80", "Coverage90"]] *= 100
    if capacity:
        result[["MAE", "CRPS", "Bias"]] *= 100
    return result


def market_day(observed: pd.DataFrame, day: str, timezone: str) -> pd.DataFrame:
    """A full 92/96/100-slot delivery grid; unavailable observations stay missing."""
    start = pd.Timestamp(day, tz=timezone)
    stop = start + pd.DateOffset(days=1)
    index = pd.date_range(
        start.tz_convert("UTC"), stop.tz_convert("UTC"), freq="15min", inclusive="left"
    )
    if observed.empty:
        return pd.DataFrame(index=index)
    return observed.set_index("valid_time").reindex(index)


def choose_curve(
    forecasts: pd.DataFrame, target: str, day: str, model: str | None = None
) -> pd.DataFrame:
    if forecasts.empty:
        return pd.DataFrame()
    rows = forecasts[(forecasts.target == target) & (forecasts.delivery_date == day)]
    if model:
        rows = rows[rows.model == model]
    if rows.empty:
        return rows
    # A target/model/day can have several genuine published revisions. The initial
    # overview shows the latest one, with its actual publication status displayed.
    if (rows.split == "Published archive").any():
        rows = rows[rows.split == "Published archive"]
        latest = rows.sort_values("published_at").forecast_id.iloc[-1]
        rows = rows[rows.forecast_id == latest]
    elif (rows.split == "Final holdout").any():
        rows = rows[rows.split == "Final holdout"]
    return rows.sort_values("valid_time")


def complete_hourly(frame: pd.DataFrame) -> pd.DataFrame:
    """Hourly mean power/price only where all four quarter-hour slots are present."""
    numeric = frame.select_dtypes(include=[np.number])
    return numeric.resample("h").mean().where(numeric.resample("h").count() == 4)
