"""Assemble the design matrix, and track where every column's information came from.

Leakage is failure mode number one here, so provenance is not a comment: each feature
column declares the latest instant its value could depend on, and the leakage test
asserts that instant never postdates the issue time.
"""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from renewable_forecast import paths, windows
from renewable_forecast.features import sites, wind
from renewable_forecast.sources import fleet, meps, openmeteo

logger = logging.getLogger(__name__)

#: Open-Meteo offsets are whole days of information age.
OFFSET_STEP = timedelta(hours=24)

#: Marks a column sourced from a named MEPS run rather than a whole-day offset. Such a
#: column's information age is `valid_time - run_time`, which varies smoothly with lead
#: time instead of stepping mid-delivery-day.
MEPS_MARKER = "__meps"
MEPS_RUN_COLUMN = "meps_run_time"


def is_meps_column(column: str) -> bool:
    """Whether a design-matrix column's information comes from a MEPS run."""
    return MEPS_MARKER in column or column == MEPS_RUN_COLUMN


#: Offsets available in the archive. The smallest *safe* one is chosen per target hour:
#: a forecast issued 09:00 UTC on D for delivery on D+1 needs an age of 14-37 h, so
#: `previous_day1` is legitimate for only the first 11 hours of the delivery day and
#: `previous_day2` must carry the rest. Using day1 throughout leaks -- the leakage test
#: catches it on 13 of every 24 rows.
AVAILABLE_OFFSETS = (1, 2)

#: The latest target hour sits 37 h after issue, so any lagged actual must be at least
#: that stale. A 24 h lag looks safe and is not: it leaks on 13 of every 24 delivery
#: hours, exactly as the fixed NWP offset did.
ACTUALS_MIN_AGE = timedelta(hours=48)

#: Lagged actuals offered to the model, all at or beyond the minimum safe age.
ACTUAL_LAGS_H = (48, 72, 168)


def _provenance(columns: list[str]) -> dict[str, timedelta | None]:
    """Latest information age each column may depend on, relative to its valid time.

    `None` means the column is knowable arbitrarily far in advance -- calendar terms and
    the lead hour itself.
    """
    always_known = {
        "hour_sin",
        "hour_cos",
        "doy_sin",
        "doy_cos",
        "lead_hour",
        "valid_time",
        "delivery_day",
        "issue_day",
        "season",
    }
    provenance: dict[str, timedelta | None] = {}
    for column in columns:
        if column in always_known:
            provenance[column] = None
        elif column.startswith("cf_lag_"):
            provenance[column] = timedelta(hours=int(column.rsplit("_", 1)[1]))
        else:
            # Both remaining cases are refined per row by `max_source_time`: Open-Meteo
            # columns by their chosen whole-day offset, MEPS columns by their run time.
            provenance[column] = OFFSET_STEP
    return provenance


def required_offset(valid_time: pd.Series, issue_time: pd.Series) -> pd.Series:
    """Smallest whole-day information age that does not postdate the issue time."""
    age_hours = (valid_time - issue_time).dt.total_seconds() / 3600
    return np.ceil(age_hours / 24).clip(lower=1).astype(int)


def issue_time_of(frame: pd.DataFrame) -> pd.Series:
    """The instant each row's forecast was issued."""
    return frame.issue_day.dt.tz_localize("UTC") + pd.Timedelta(
        hours=windows.ISSUE_HOUR_UTC
    )


def calendar(frame: pd.DataFrame) -> pd.DataFrame:
    """Cyclical time-of-day and time-of-year terms.

    Deliberately no raw datetime as a numeric: a tree would happily split on it and then
    fail on every date it has not seen.
    """
    local = frame.valid_time.dt.tz_convert(windows.MARKET_TZ)
    hour = local.dt.hour + local.dt.minute / 60
    doy = local.dt.dayofyear
    return pd.DataFrame(
        {
            "hour_sin": np.sin(2 * np.pi * hour / 24),
            "hour_cos": np.cos(2 * np.pi * hour / 24),
            "doy_sin": np.sin(2 * np.pi * doy / 365.25),
            "doy_cos": np.cos(2 * np.pi * doy / 365.25),
        },
        index=frame.index,
    )


def multi_model(zonal: pd.DataFrame) -> pd.DataFrame:
    """Pivot per-model zonal features side by side and add cross-model spread.

    Disagreement between independent forecast providers is the uncertainty signal that
    is actually available retroactively -- a true ensemble archive is not.
    """
    value_columns = [c for c in zonal.columns if c not in {"model", "valid_time"}]
    wide = zonal.pivot(index="valid_time", columns="model", values=value_columns)
    wide.columns = [f"{var}__{model}" for var, model in wide.columns]

    out = wide.reset_index()
    for column in ("power_curve", "wind_speed_100m"):
        members = [c for c in wide.columns if c.startswith(f"{column}__")]
        if len(members) < 2:
            continue
        values = wide[members].to_numpy(dtype=float)
        out[f"{column}_model_mean"] = np.nanmean(values, axis=1)
        out[f"{column}_model_std"] = np.nanstd(values, axis=1)
        out[f"{column}_model_range"] = np.nanmax(values, axis=1) - np.nanmin(
            values, axis=1
        )
    return out


def temporal(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """Lags, leads and ramps of the key NWP features.

    These describe the weather trajectory around the target hour, which at a fixed lead
    time carries real information beyond the instantaneous value.
    """
    out = pd.DataFrame(index=frame.index)
    for column in columns:
        if column not in frame.columns:
            continue
        series = frame[column]
        for shift in (-3, -1, 1, 3):
            out[f"{column}_shift{shift:+d}"] = series.shift(shift)
        out[f"{column}_ramp1"] = series.diff(1)
        out[f"{column}_ramp3"] = series.diff(3)
        out[f"{column}_roll6_mean"] = series.rolling(6, min_periods=1).mean()
        out[f"{column}_roll6_std"] = series.rolling(6, min_periods=2).std()
    return out


def _features_at(raw: pd.DataFrame, points: pd.DataFrame, offset: int) -> pd.DataFrame:
    """Zonal, multi-model features at one information-age offset."""
    per_point = wind.add_icing_memory(wind.per_point(raw, offset))
    zonal = wind.aggregate(per_point, points)
    frame = multi_model(zonal).sort_values("valid_time").reset_index(drop=True)
    trajectory = temporal(
        frame, ("power_curve_model_mean", "wind_speed_100m_model_mean")
    )
    frame = pd.concat([frame, trajectory], axis=1)
    frame["nwp_offset_days"] = offset
    return frame


#: Trajectory features are derived for these MEPS columns, mirroring the Open-Meteo
#: pair so the two blocks stay comparable.
MEPS_TRAJECTORY = ("power_curve__meps", "wind_speed_hub__meps")


def meps_block(points: pd.DataFrame) -> pd.DataFrame:
    """Zonal MEPS features, keyed by the run that produced them.

    The contrast with `_features_at` is the whole point of this source. There, a row's
    information age is a whole number of days and *changes partway through the delivery
    day*, because the archive can only be asked for whole-day offsets. Here a row
    belongs to a named 00z run, and one run covers the entire delivery day, so the age
    varies smoothly with lead time exactly as the physics does.

    Returns one row per `(run_time, valid_time)`, with columns suffixed `__meps` so they
    sit unambiguously alongside the Open-Meteo blocks.
    """
    raw = meps.load()
    if raw.empty:
        msg = "no MEPS data parsed; run pipelines.pull_meps first"
        raise RuntimeError(msg)

    per_point = wind.add_icing_memory(
        wind.per_point_meps(raw, points), keys=("run_time", "point_id")
    )
    zonal = wind.aggregate(
        per_point,
        points,
        keys=("run_time", "valid_time"),
        dispersion=("wind_speed_hub", "power_curve"),
    )
    zonal = zonal.rename(
        columns={
            c: f"{c}__meps"
            for c in zonal.columns
            if c not in {"run_time", "valid_time"}
        }
    )

    zonal = zonal.sort_values(["run_time", "valid_time"]).reset_index(drop=True)
    # Trajectories are computed within a run, never across the join between two, which
    # is why this groups rather than shifting the whole frame.
    trajectory = (
        zonal.groupby("run_time", group_keys=False)
        .apply(lambda g: temporal(g, MEPS_TRAJECTORY), include_groups=False)
        .reindex(zonal.index)
    )
    return pd.concat([zonal, trajectory], axis=1)


def attach_meps(frame: pd.DataFrame, points: pd.DataFrame) -> pd.DataFrame:
    """Join the MEPS block onto a design matrix that already carries `issue_day`.

    A delivery day is served by exactly one run -- 00z on its issue day -- so this is an
    equality join on the run instant, with no offset to choose and nothing to decide per
    hour.
    """
    block = meps_block(points)
    frame = frame.copy()
    frame["meps_run_time"] = frame.issue_day.dt.tz_localize("UTC") + pd.Timedelta(
        hours=meps.RUN_HOUR_UTC
    )
    merged = frame.merge(
        block,
        left_on=["meps_run_time", "valid_time"],
        right_on=["run_time", "valid_time"],
        how="left",
    ).drop(columns=["run_time"])
    missing = merged["power_curve__meps"].isna().sum()
    if missing:
        logger.warning("%s of %s rows have no MEPS coverage", missing, len(merged))
    return merged


def build(zone: str = "SE3", fuel: str = "wind_onshore") -> pd.DataFrame:
    """Join NWP features to the target, picking the smallest safe offset per hour."""
    raw = openmeteo.load()
    if raw.empty:
        msg = "no NWP data parsed; run openmeteo.pull first"
        raise RuntimeError(msg)

    points = sites.build(zone)
    stacked = pd.concat(
        [_features_at(raw, points, offset) for offset in AVAILABLE_OFFSETS],
        ignore_index=True,
    )

    targets = pd.read_parquet(paths.INTERIM / f"targets_{zone.lower()}_{fuel}.parquet")
    targets["period_start"] = pd.to_datetime(targets.period_start, utc=True)
    targets = targets[targets.trainable].rename(columns={"period_start": "valid_time"})

    targets = _annotate(targets)

    history = targets.set_index("valid_time").cf
    for lag in ACTUAL_LAGS_H:
        targets[f"cf_lag_{lag}"] = (targets.valid_time - pd.Timedelta(hours=lag)).map(
            history
        )

    keep = [
        "valid_time",
        "cf",
        "mw",
        "capacity_mw",
        "delivery_day",
        "issue_day",
        "season",
        "lead_hour",
        "nwp_offset_days",
        *[f"cf_lag_{lag}" for lag in ACTUAL_LAGS_H],
    ]
    merged = targets[keep].merge(
        stacked, on=["valid_time", "nwp_offset_days"], how="inner"
    )
    return pd.concat([merged, calendar(merged)], axis=1)


def _annotate(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the delivery-day, season, lead-hour and offset columns shared by both paths."""
    local = frame.valid_time.dt.tz_convert(windows.MARKET_TZ)
    frame["delivery_day"] = local.dt.normalize().dt.tz_localize(None)
    frame["issue_day"] = frame.delivery_day - pd.Timedelta(days=1)
    frame["season"] = local.dt.month.map(
        lambda m: ["DJF", "MAM", "JJA", "SON"][(m % 12) // 3]
    )
    frame["lead_hour"] = (
        (frame.valid_time - frame.issue_day.dt.tz_localize("UTC")).dt.total_seconds()
        // 3600
    ).astype(int)
    frame["nwp_offset_days"] = required_offset(frame.valid_time, issue_time_of(frame))
    return frame


def build_operational(
    delivery_day: date, zone: str = "SE3", fuel: str = "wind_onshore"
) -> pd.DataFrame:
    """Design matrix for one future delivery day, with no target column.

    Identical in construction to `build` -- same offsets, same lags, same calendar --
    so the operational path cannot drift away from the trained one. The only
    differences are that `cf` is unknown and the capacity denominator is frozen at the
    issue day rather than read from the target table.
    """
    raw = openmeteo.load()
    if raw.empty:
        msg = "no NWP data parsed; run openmeteo.pull first"
        raise RuntimeError(msg)

    points = sites.build(zone)
    stacked = pd.concat(
        [_features_at(raw, points, offset) for offset in AVAILABLE_OFFSETS],
        ignore_index=True,
    )

    grid = pd.DataFrame({"valid_time": windows.delivery_day_starts(delivery_day)})
    grid["valid_time"] = pd.to_datetime(grid.valid_time, utc=True)
    grid = _annotate(grid)

    turbines = fleet.load_turbines()
    series = fleet.capacity_series(turbines, zone)
    grid["capacity_mw"] = fleet.capacity_at(series, grid.issue_day.iloc[0].date())

    targets = pd.read_parquet(paths.INTERIM / f"targets_{zone.lower()}_{fuel}.parquet")
    targets["period_start"] = pd.to_datetime(targets.period_start, utc=True)
    history = targets.set_index("period_start").cf
    for lag in ACTUAL_LAGS_H:
        grid[f"cf_lag_{lag}"] = (grid.valid_time - pd.Timedelta(hours=lag)).map(history)

    merged = grid.merge(stacked, on=["valid_time", "nwp_offset_days"], how="left")
    merged = pd.concat([merged, calendar(merged)], axis=1)
    missing = merged.power_curve_model_mean.isna().sum()
    if missing:
        logger.warning("%s of %s hours have no NWP coverage", missing, len(merged))
    return merged


def provenance(frame: pd.DataFrame) -> dict[str, timedelta | None]:
    """Declared information age for every feature column in a design matrix."""
    excluded = {"cf", "mw", "capacity_mw"}
    return _provenance([c for c in frame.columns if c not in excluded])


def max_source_time(frame: pd.DataFrame) -> pd.DataFrame:
    """Latest instant each column's value may depend on, per row.

    This is what the leakage test compares against the issue time.
    """
    ages = provenance(frame)
    if "nwp_offset_days" in frame.columns:
        nwp_age = pd.to_timedelta(frame.nwp_offset_days * 24, unit="h")
    else:
        nwp_age = pd.Series([OFFSET_STEP] * len(frame), index=frame.index)

    run_time = frame[MEPS_RUN_COLUMN] if MEPS_RUN_COLUMN in frame.columns else None

    out = pd.DataFrame(index=frame.index)
    for column, age in ages.items():
        if age is None:
            out[column] = pd.Timestamp.min.tz_localize("UTC")
        elif column.startswith("cf_lag_"):
            out[column] = frame.valid_time - age
        elif is_meps_column(column) and run_time is not None:
            # A MEPS column depends on nothing later than the run that produced it.
            out[column] = run_time
        else:
            out[column] = frame.valid_time - nwp_age
    return out


def write(zone: str = "SE3", fuel: str = "wind_onshore") -> pd.DataFrame:
    """Build the design matrix and persist it."""
    frame = build(zone, fuel)
    paths.FEATURES.mkdir(parents=True, exist_ok=True)
    out = paths.FEATURES / f"design_matrix_{zone.lower()}_{fuel}.parquet"
    frame.to_parquet(out, index=False)
    logger.info("wrote %s (%s rows, %s columns)", out, len(frame), frame.shape[1])
    return frame
