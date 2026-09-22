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
from renewable_forecast.sources import entsoe, fleet, ifs_runs, meps, openmeteo

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


#: Marks a column from a named ECMWF IFS HRES run (`sources.ifs_runs`). Dated to the
#: run's *availability*, not its initialisation, so the leakage guard also checks that
#: the run existed before the issue time.
IFS_MARKER = "__ifsrun"
IFS_RUN_COLUMN = "ifs_run_time"


def is_ifs_column(column: str) -> bool:
    """Whether a design-matrix column's information comes from an IFS single run."""
    return IFS_MARKER in column or column == IFS_RUN_COLUMN


#: Cross-source spread over the run-addressed sources. The Open-Meteo `*_model_std`
#: columns measure disagreement between whole-day-vintaged models, which goes away if
#: that block is dropped; this is its run-addressed replacement.
RUN_SPREAD_PREFIX = "power_curve_runs_"


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


#: Trajectory features for the IFS run block, mirroring the other two sources.
IFS_TRAJECTORY = ("power_curve__ifsrun", "wind_speed_100m__ifsrun")


def ifs_block(
    points: pd.DataFrame, run_hour: int = ifs_runs.RUN_HOUR_UTC
) -> pd.DataFrame:
    """Zonal IFS HRES features keyed by the run that produced them.

    The physics is the Open-Meteo path's (`wind.per_point`), since the variables are
    the same; only the addressing differs, which is the point of the source.
    """
    raw = ifs_runs.load()
    if not raw.empty:
        raw = raw[pd.to_datetime(raw.run_time, utc=True).dt.hour == run_hour]
    if raw.empty:
        msg = f"no {run_hour:02d}z IFS runs parsed; run pipelines.pull_ifs_runs first"
        raise RuntimeError(msg)

    per_point = wind.add_icing_memory(
        wind.per_point(raw, suffix=""), keys=("run_time", "point_id")
    )
    per_point = per_point.drop(columns=["lead_spread"], errors="ignore")
    zonal = wind.aggregate(per_point, points, keys=("run_time", "valid_time"))
    zonal = zonal.rename(
        columns={
            c: f"{c}{IFS_MARKER}"
            for c in zonal.columns
            if c not in {"run_time", "valid_time"}
        }
    )
    zonal = zonal.sort_values(["run_time", "valid_time"]).reset_index(drop=True)
    trajectory = (
        zonal.groupby("run_time", group_keys=False)
        .apply(lambda g: temporal(g, IFS_TRAJECTORY), include_groups=False)
        .reindex(zonal.index)
    )
    return pd.concat([zonal, trajectory], axis=1)


def attach_ifs(
    frame: pd.DataFrame, points: pd.DataFrame, *, lagged: bool = True
) -> pd.DataFrame:
    """Join the IFS run block on the issue day's 00z run, exactly as for MEPS.

    With `lagged`, also the previous day's 18z run and the change between the two.
    """
    block = ifs_block(points)
    frame = frame.copy()
    frame[IFS_RUN_COLUMN] = frame.issue_day.dt.tz_localize("UTC") + pd.Timedelta(
        hours=ifs_runs.RUN_HOUR_UTC
    )
    merged = frame.merge(
        block,
        left_on=[IFS_RUN_COLUMN, "valid_time"],
        right_on=["run_time", "valid_time"],
        how="left",
    ).drop(columns=["run_time"])
    missing = merged[f"power_curve{IFS_MARKER}"].isna().sum()
    if missing:
        logger.warning("%s of %s rows have no IFS run coverage", missing, len(merged))
    if lagged:
        merged = _attach_lagged_ifs(merged, points)
    return merged


#: Columns taken from the previous day's 18z run. Kept few: they exist to measure how
#: much the forecast changed between cycles, not to add a second copy of the weather.
LAGGED_COLUMNS = ("power_curve", "wind_speed_100m")
LAG_SUFFIX = "_lag6"


def _attach_lagged_ifs(frame: pd.DataFrame, points: pd.DataFrame) -> pd.DataFrame:
    """Join the 18z run from the day before the issue day, and the 00z - 18z change.

    Run-to-run change is a time-lagged ensemble of two members. It carries the IFS
    marker, so the leakage guard dates it to the 00z run's availability -- later than
    the 18z run's own, hence conservative.
    """
    try:
        block = ifs_block(points, ifs_runs.LAGGED_RUN_HOUR_UTC)
    except RuntimeError:
        logger.warning("no 18z IFS runs parsed; lagged IFS features skipped")
        return frame
    keep = {f"{c}{IFS_MARKER}": f"{c}{IFS_MARKER}{LAG_SUFFIX}" for c in LAGGED_COLUMNS}
    block = block[["run_time", "valid_time", *keep]].rename(columns=keep)
    lag_run = frame[IFS_RUN_COLUMN] - pd.Timedelta(hours=24 - ifs_runs.LAGGED_RUN_HOUR_UTC)
    merged = frame.assign(_lag_run=lag_run).merge(
        block,
        left_on=["_lag_run", "valid_time"],
        right_on=["run_time", "valid_time"],
        how="left",
    ).drop(columns=["_lag_run", "run_time"])
    for column in LAGGED_COLUMNS:
        now = merged[f"{column}{IFS_MARKER}"]
        before = merged[f"{column}{IFS_MARKER}{LAG_SUFFIX}"]
        merged[f"{column}{IFS_MARKER}_jump"] = now - before
        merged[f"{column}{IFS_MARKER}_jump_abs"] = (now - before).abs()
    return merged


def run_spread(frame: pd.DataFrame) -> pd.DataFrame:
    """Mean and disagreement of power-curve output across the run-addressed sources.

    Carries the same information age as its inputs, so it is marked as both a MEPS and
    an IFS column and the leakage guard dates it to the later of the two.
    """
    members = [c for c in ("power_curve__meps", f"power_curve{IFS_MARKER}") if c in frame]
    out = pd.DataFrame(index=frame.index)
    if len(members) < 2:
        return out
    values = frame[members].to_numpy(dtype=float)
    stem = f"{RUN_SPREAD_PREFIX}{{}}{MEPS_MARKER}{IFS_MARKER}"
    out[stem.format("mean")] = values.mean(axis=1)
    out[stem.format("std")] = values.std(axis=1)
    return out


#: Columns derived from the issue day's day-ahead auction. That auction cleared about
#: 12:45 CET the day *before* the issue day, so every one of its hours is known well
#: before 09:00 UTC on the issue day -- even hours that are still in the future then.
#: They are dated to 00:00 UTC on the issue day: later than the true publication (so
#: conservative) and earlier than the issue time.
PRICE_PREFIX = "price_issue_day_"


def is_price_column(column: str) -> bool:
    """Whether a column comes from the issue day's day-ahead auction."""
    return column.startswith(PRICE_PREFIX)


def price_features(frame: pd.DataFrame, zone: str = "SE3") -> pd.DataFrame:
    """Curtailment-risk features from the issue day's already-published prices.

    Negative prices make operators curtail, and the ERA5 study measured a +184 MW
    over-prediction on those hours (`reports/era5_ceiling.md` section 4). The delivery
    day's prices are not known at 09:00 on the issue day; the issue day's are, and
    negative-price regimes persist across adjacent days.
    """
    prices = entsoe.load("day_ahead_prices", zone)
    series = (
        prices.assign(period_start=pd.to_datetime(prices.period_start, utc=True))
        .set_index("period_start")
        .value_mw.sort_index()
    )
    # 15-minute auction results from October 2025 are averaged to the hour, matching
    # the target's resolution.
    hourly = series.resample("h").mean()

    out = pd.DataFrame(index=frame.index)
    out[f"{PRICE_PREFIX}same_hour"] = (
        frame.valid_time - pd.Timedelta(hours=24)
    ).map(hourly).to_numpy()

    local_day = hourly.index.tz_convert(windows.MARKET_TZ).normalize().tz_localize(None)
    daily = hourly.groupby(local_day).agg(
        min="min", mean="mean", negative_hours=lambda v: float((v < 0).sum())
    )
    for name in daily.columns:
        out[f"{PRICE_PREFIX}{name}"] = frame.issue_day.map(daily[name]).to_numpy()
    return out


def attach_prices(frame: pd.DataFrame, zone: str = "SE3") -> pd.DataFrame:
    """Append the price block to an existing design matrix."""
    return pd.concat([frame, price_features(frame, zone)], axis=1)


#: Columns built from generation observed shortly before issue. The last hour used
#: ends RESIDUAL_MARGIN before the issue time, which leaves ENTSO-E's one-hour
#: publication deadline plus an hour of slack.
RESIDUAL_PREFIX = "recent_resid_"
RESIDUAL_MARGIN = timedelta(hours=2)
RESIDUAL_WINDOWS_H = (8, 24, 72)

#: The residual has a large standing offset (physics under-predicts by ~0.05 CF) that
#: the model already learns from the level features. What it cannot learn is the
#: *departure* from that offset, so each window is expressed against this baseline.
#: Measured on the backtest: day-level correlation with the model's error rises from
#: 0.04-0.07 for the raw residual to 0.13-0.17 for the anomaly.
RESIDUAL_BASELINE = "30D"


def is_residual_column(column: str) -> bool:
    """Whether a column depends on generation observed on the issue day."""
    return column.startswith(RESIDUAL_PREFIX)


def residual_features(frame: pd.DataFrame, zone: str = "SE3") -> pd.DataFrame:
    """How far the physics has been off in the hours just before issue.

    Daily mean error is autocorrelated (0.32 at one day, `reports/calibration.md`), and
    the only generation the model otherwise sees is at least 48 h old. The residual is
    observed CF minus the capacity-weighted power curve at Open-Meteo offset 1, whose
    values for issue-day hours were published the day before.

    Generation-derived features inherit every redispatch and outage in the data
    (Meisenbacher et al. 2025), so the residual is clipped rather than trusted raw.
    """
    fuel = "wind_onshore"
    targets = pd.read_parquet(paths.INTERIM / f"targets_{zone.lower()}_{fuel}.parquet")
    observed = targets.assign(
        valid_time=pd.to_datetime(targets.period_start, utc=True)
    ).set_index("valid_time").cf

    physics = _features_at(openmeteo.load(), sites.build(zone), 1).set_index(
        "valid_time"
    ).power_curve_model_mean
    residual = (observed - physics).dropna().clip(-0.3, 0.3).sort_index()
    residual = residual.resample("h").mean()

    # The value an hour-start label carries is known once the hour has ended.
    last_start = issue_time_of(frame) - RESIDUAL_MARGIN - pd.Timedelta(hours=1)
    baseline = residual.rolling(RESIDUAL_BASELINE, min_periods=100).mean()
    out = pd.DataFrame(index=frame.index)
    for window in RESIDUAL_WINDOWS_H:
        rolled = residual.rolling(f"{window}h", min_periods=window // 2).mean()
        out[f"{RESIDUAL_PREFIX}{window}h_anom"] = last_start.map(
            rolled - baseline
        ).to_numpy()
    return out


def attach_residuals(frame: pd.DataFrame, zone: str = "SE3") -> pd.DataFrame:
    """Append the recent-residual block to an existing design matrix."""
    return pd.concat([frame, residual_features(frame, zone)], axis=1)


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


def build(
    zone: str = "SE3",
    fuel: str = "wind_onshore",
    *,
    with_meps: bool = False,
    with_ifs: bool = False,
) -> pd.DataFrame:
    """Join NWP features to the target, picking the smallest safe offset per hour.

    `with_meps` appends the run-addressed MEPS block. It is additive by design: the row
    set is untouched, so a matrix built with it supports an exact A/B -- the same rows,
    scored with and without the `__meps` columns -- rather than a comparison confounded
    by differing coverage.
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
    merged = pd.concat([merged, calendar(merged)], axis=1)
    if with_meps:
        merged = attach_meps(merged, points)
    if with_ifs:
        merged = attach_ifs(merged, points)
    if with_meps and with_ifs:
        merged = pd.concat([merged, run_spread(merged)], axis=1)
    return merged


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


#: Run-addressed sources a config may name under `features.run_addressed`, mapped to
#: the column that says whether a row has that source.
RUN_SOURCES = {"meps": "power_curve__meps", "ifs_runs": f"power_curve{IFS_MARKER}"}


def run_flags(sources: list[str] | tuple[str, ...]) -> dict[str, bool]:
    """`build` keyword arguments for a list of configured run-addressed sources."""
    unknown = set(sources) - set(RUN_SOURCES)
    if unknown:
        msg = f"unknown run-addressed sources {sorted(unknown)}"
        raise ValueError(msg)
    return {"with_meps": "meps" in sources, "with_ifs": "ifs_runs" in sources}


def require_run_coverage(
    frame: pd.DataFrame, sources: list[str] | tuple[str, ...]
) -> pd.DataFrame:
    """Keep only delivery days on which every configured run-addressed source exists.

    A model fitted across days with and without a source learns two regimes, and its
    calibration block -- the most recent quarter of the window -- may fall entirely in
    the one the live forecast is *not* in. Whole days are kept or dropped, never hours.
    """
    columns = [RUN_SOURCES[s] for s in sources if RUN_SOURCES[s] in frame.columns]
    if not columns:
        return frame
    have = frame[columns].notna().all(axis=1)
    complete = have.groupby(frame.delivery_day).transform("all")
    dropped = frame.loc[~complete, "delivery_day"].nunique()
    if dropped:
        logger.info("%s delivery days lack a run-addressed source; dropped", dropped)
    return frame[complete].reset_index(drop=True)


def build_operational(
    delivery_day: date,
    zone: str = "SE3",
    fuel: str = "wind_onshore",
    *,
    with_meps: bool = False,
    with_ifs: bool = False,
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
    # The same attach functions as `build`, so the live row carries exactly the columns
    # the model was fitted on.
    if with_meps:
        merged = attach_meps(merged, points)
    if with_ifs:
        merged = attach_ifs(merged, points)
    if with_meps and with_ifs:
        merged = pd.concat([merged, run_spread(merged)], axis=1)
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
    ifs_available = (
        frame[IFS_RUN_COLUMN] + ifs_runs.AVAILABILITY_LAG
        if IFS_RUN_COLUMN in frame.columns
        else None
    )

    out = pd.DataFrame(index=frame.index)
    for column, age in ages.items():
        if age is None:
            out[column] = pd.Timestamp.min.tz_localize("UTC")
        elif column.startswith("cf_lag_"):
            out[column] = frame.valid_time - age
        elif is_residual_column(column):
            out[column] = issue_time_of(frame) - RESIDUAL_MARGIN
        elif is_price_column(column):
            out[column] = frame.issue_day.dt.tz_localize("UTC")
        elif is_ifs_column(column) and ifs_available is not None:
            # Checked before MEPS so a column derived from both sources is dated to
            # the later one: IFS availability is always after the MEPS run instant.
            out[column] = ifs_available
        elif is_meps_column(column) and run_time is not None:
            # A MEPS column depends on nothing later than the run that produced it.
            out[column] = run_time
        else:
            out[column] = frame.valid_time - nwp_age
    return out


def design_matrix_path(
    zone: str = "SE3",
    fuel: str = "wind_onshore",
    *,
    with_meps: bool = False,
    with_ifs: bool = False,
):
    """Where a design matrix of the given flavour lives."""
    suffix = ("_meps" if with_meps else "") + ("_ifs" if with_ifs else "")
    return paths.FEATURES / f"design_matrix_{zone.lower()}_{fuel}{suffix}.parquet"


def write(
    zone: str = "SE3",
    fuel: str = "wind_onshore",
    *,
    with_meps: bool = False,
    with_ifs: bool = False,
) -> pd.DataFrame:
    """Build the design matrix and persist it."""
    frame = build(zone, fuel, with_meps=with_meps, with_ifs=with_ifs)
    paths.FEATURES.mkdir(parents=True, exist_ok=True)
    out = design_matrix_path(zone, fuel, with_meps=with_meps, with_ifs=with_ifs)
    frame.to_parquet(out, index=False)
    logger.info("wrote %s (%s rows, %s columns)", out, len(frame), frame.shape[1])
    return frame
