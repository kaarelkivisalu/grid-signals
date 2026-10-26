"""Portable market data and interval-weighted diagnostics; no research dependencies."""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from grid_signals.app.snapshot import SnapshotError

DEFAULT_ROOT = Path(__file__).parent / "assets/explorer"
SCORED_SPLITS = ("Final holdout", "Development")
GROUPS = ("Overall", "Year", "Season", "Month", "Weekday", "Market quarter")


def bundle_root() -> Path:
    return Path(os.environ.get("GRID_SIGNALS_EXPLORER_PATH", DEFAULT_ROOT))


def load_manifest() -> dict:
    try:
        payload = json.loads((bundle_root() / "manifest.json").read_text())
        if payload["schema_version"] != 1 or not payload["zones"]:
            raise ValueError  # noqa: TRY301
        for info in payload["zones"].values():
            for key in ("forecast_file", "observation_file"):
                name = info[key]
                if name and (Path(name).name != name or not name.endswith(".parquet")):
                    raise ValueError  # noqa: TRY301
    except (OSError, KeyError, TypeError, ValueError) as exc:
        message = "The market explorer bundle is missing or incompatible."
        raise SnapshotError(message) from exc
    else:
        return payload


@st.cache_data(show_spinner=False, max_entries=40)
def _read_artifact(root: str, filename: str, kind: str) -> pd.DataFrame:
    frame = pd.read_parquet(Path(root) / filename)
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
    name = manifest["zones"].get(zone, {}).get(f"{kind}_file")
    if not name:
        return pd.DataFrame()
    try:
        return _read_artifact(str(bundle_root()), name, kind)
    except (OSError, ValueError) as exc:
        message = "This market's exported data is unavailable."
        raise SnapshotError(message) from exc


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
