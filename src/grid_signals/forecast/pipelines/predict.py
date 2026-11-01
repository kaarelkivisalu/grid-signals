"""Produce an operational forecast for a delivery day whose actuals do not exist yet.

This is the path a scheduled 09:00 UTC job would run. It differs from the backtest in
exactly two ways, both deliberate:

- It fits on **every** trainable day available at issue time, not on a rolling-origin
  training window. That is correct for production and means this model is *not* the one
  the sealed holdout will score -- holdout scoring refits from folds that exclude it.
- There is no target column to score against, so the output is a forecast vintage
  rather than a row on the leaderboard.

Everything else -- offsets, lags, calendar, the capacity denominator -- comes from the
same functions the training path uses, so the two cannot drift apart.
"""

import argparse
import logging
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from grid_signals.forecast import config, paths, publication, windows
from grid_signals.forecast.features import assemble, sites, solar
from grid_signals.forecast.features.resolution import validate
from grid_signals.forecast.models.quantile import QuantileGBM
from grid_signals.forecast.models.solar import SolarQuantileGBM
from grid_signals.forecast.sources import ifs_runs, meps, openmeteo

logger = logging.getLogger(__name__)

#: Forecast vintages are append-only. Display may choose the newest revision;
#: operational scoring always uses the first eligible publication instead.
VINTAGES = paths.PREDICTIONS / "forecast_vintages.parquet"

#: Extra days of NWP to refresh either side of the delivery day, so the temporal
#: features (lags and ramps) have neighbours to work with at the window edges.
CONTEXT_DAYS = 1


def refresh_nwp(
    delivery_day: date, zone: str = "SE3", run_addressed: tuple[str, ...] = ()
) -> None:
    """Pull the newest NWP covering the delivery day, merging into the archive.

    Run-addressed sources are fetched for the issue day's 00z run only. Each call also
    self-archives that run. That is cheap insurance: during MET Norway's storeB network
    maintenance (2026-09-22/23) the thredds MEPS archive served only the current month,
    and a forecast must not depend on an archive being reachable later.
    """
    points = sites.build(zone)
    openmeteo.pull(
        points,
        start=delivery_day - timedelta(days=CONTEXT_DAYS),
        end=delivery_day + timedelta(days=CONTEXT_DAYS + 1),
        merge=True,
    )
    issue_day = delivery_day - timedelta(days=1)
    if "meps" in run_addressed:
        meps.pull(points, issue_day, delivery_day)
    if "ifs_runs" in run_addressed:
        ifs_runs.pull(points, issue_day, delivery_day)


def run(
    delivery_day: date | None = None,
    zone: str = "SE3",
    fuel: str = "wind_onshore",
    *,
    refresh: bool = True,
    resolution: str = "15min",
    wind_method: str = "repeat",
) -> pd.DataFrame:
    """Forecast one delivery day and append the vintage. Defaults to tomorrow."""
    from grid_signals.forecast import versions

    release = versions.verify()
    started = publication.now()
    delivery_day = delivery_day or (datetime.now(UTC).date() + timedelta(days=1))
    issue_day = delivery_day - timedelta(days=1)
    issued = windows.issue_time(issue_day)
    step = validate(resolution)
    from grid_signals.products import renewable_product

    renewable_product(zone, fuel)
    is_solar = (zone, fuel) == ("DE_LU", "solar")
    if wind_method not in {"repeat", "interpolate"}:
        raise ValueError("wind_method must be repeat or interpolate")
    if not is_solar and (zone, fuel) != ("SE3", "wind_onshore"):
        raise ValueError("supported tasks: SE3 wind_onshore and DE_LU solar")
    cfg = config.load("delu_solar" if is_solar else None)
    cfg.task.zone = zone
    cfg.task.fuel_types = [fuel]
    cfg.task.resolution = resolution
    if is_solar:
        temporal_method = "native"
    elif step == pd.Timedelta("1h"):
        temporal_method = "hourly"
    else:
        temporal_method = {
            "repeat": "hourly_repeated",
            "interpolate": "interpolated_weather",
        }[wind_method]
    cfg.features["temporal_method"] = temporal_method
    levels = np.array(cfg.task.quantiles)

    run_addressed = tuple(cfg.features.get("run_addressed", ()))
    flags = assemble.run_flags(run_addressed)
    if refresh:
        if is_solar:
            solar.refresh(delivery_day)
        else:
            refresh_nwp(delivery_day, zone, run_addressed)

    future = (
        solar.build(delivery_day, resolution)
        if is_solar
        else assemble.build_operational(
            delivery_day,
            zone,
            fuel,
            resolution="1h" if temporal_method == "hourly_repeated" else resolution,
            **flags,
        )
    )
    required = (
        ["physical_cf", "clear_sky_cf", "solar_elevation"]
        if is_solar
        else [
            "power_curve_model_mean",
            *[assemble.RUN_SOURCES[source] for source in run_addressed],
        ]
    )
    if future[required].isna().any().any():
        raise RuntimeError(
            f"incomplete weather coverage for {zone} {delivery_day}; cannot forecast"
        )
    if is_solar:
        train = solar.build(resolution=resolution)
    else:
        # Stage 1: train on hourly means; evaluate interpolated NWP with that model.
        train = assemble.require_run_coverage(
            assemble.build(zone, fuel, **flags), run_addressed
        )
    # Whole delivery days ending before the issue day only. A historic invocation
    # must never train on the issue day's later actuals simply because they are cached.
    train = train[train.delivery_day < pd.Timestamp(issue_day)]
    if train.empty:
        raise RuntimeError("no training history available before issue")
    logger.info(
        "fitting on %s rows up to %s", len(train), train.delivery_day.max().date()
    )
    factory = SolarQuantileGBM if is_solar else QuantileGBM
    model = factory(levels, **cfg.model.get("quantile", {})).fit(train)
    quantiles = model.predict(future)
    if temporal_method == "hourly_repeated":
        grid = pd.DatetimeIndex(
            windows.delivery_day_starts(delivery_day, resolution=step)
        )
        positions = pd.DatetimeIndex(future.valid_time).get_indexer(grid.floor("h"))
        if (positions < 0).any():
            raise RuntimeError(
                "hourly forecast does not cover the quarter-hour delivery grid"
            )
        future = future.iloc[positions].reset_index(drop=True)
        future["valid_time"] = grid
        quantiles = quantiles[positions]

    out = future[["valid_time", "delivery_day", "lead_hour", "capacity_mw"]].copy()
    out["zone"] = zone
    out["fuel_type"] = fuel
    out["resolution"] = resolution
    out["temporal_method"] = temporal_method
    out["period_end"] = out.valid_time + step
    out["issue_time"] = issued
    out["model_version"] = release["identity"] + "+" + cfg.fingerprint()
    out["created_at"] = datetime.now(UTC)
    out["daylight"] = future.solar_elevation.to_numpy() > 5 if is_solar else True
    for level, column in zip(levels, quantiles.T, strict=True):
        out[f"cf_q{level:.2f}"] = column
        out[f"mw_q{level:.2f}"] = column * out.capacity_mw

    out = publication.append(out, VINTAGES, started, _read_vintages)
    logger.info("wrote %s new rows to %s", len(out), VINTAGES)
    return out


def _read_vintages() -> pd.DataFrame:
    """Read the archive, including legacy wind-only hourly vintages."""
    if not VINTAGES.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(VINTAGES)
    for column, default in {
        "zone": "SE3",
        "fuel_type": "wind_onshore",
        "resolution": "1h",
    }.items():
        if column not in frame:
            frame[column] = default
        else:
            frame[column] = frame[column].fillna(default)
    if "period_end" not in frame:
        frame["period_end"] = frame.valid_time + pd.Timedelta(hours=1)
    # Before temporal_method was recorded, the first quarter-hour wind vintages
    # used interpolated weather; older wind was hourly and solar was always native.
    inferred = pd.Series(
        np.where(
            frame.fuel_type == "solar",
            "native",
            np.where(frame.resolution == "1h", "hourly", "interpolated_weather"),
        ),
        index=frame.index,
    )
    frame["temporal_method"] = (
        frame["temporal_method"].fillna(inferred)
        if "temporal_method" in frame
        else inferred
    )
    return publication.legacy_metadata(frame)


def latest(
    zone: str = "SE3", fuel: str = "wind_onshore", resolution: str | None = None
) -> pd.DataFrame:
    """Newest forecast for the requested task; never another zone or fuel's vintage."""
    frame = _read_vintages()
    if not frame.empty:
        frame = frame[(frame.zone == zone) & (frame.fuel_type == fuel)]
        if resolution is not None:
            frame = frame[frame.resolution == resolution]
    if frame.empty:
        raise FileNotFoundError(
            f"no forecast archived for {zone} {fuel} {resolution or ''}"
        )
    return frame[frame.created_at == frame.created_at.max()].sort_values("valid_time")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--day", type=date.fromisoformat, help="local delivery day (default tomorrow)"
    )
    parser.add_argument(
        "--fuel", choices=["wind_onshore", "solar"], default="wind_onshore"
    )
    parser.add_argument("--zone", choices=["SE3", "DE_LU"])
    parser.add_argument("--resolution", choices=["1h", "15min"], default="15min")
    parser.add_argument(
        "--wind-method",
        choices=["repeat", "interpolate"],
        default="repeat",
        help="repeat hourly distributions (default), or predict using interpolated weather",
    )
    parser.add_argument("--no-refresh", action="store_true", help="use cached weather")
    args = parser.parse_args(argv)
    zone = args.zone or ("DE_LU" if args.fuel == "solar" else "SE3")
    frame = run(
        args.day,
        zone,
        args.fuel,
        refresh=not args.no_refresh,
        resolution=args.resolution,
        wind_method=args.wind_method,
    )
    logger.info(
        "%s: mean interval forecasts p10 %.0f MW, p90 %.0f MW, p50 %.0f MW",
        frame.delivery_day.iloc[0].date(),
        frame["mw_q0.10"].mean(),
        frame["mw_q0.90"].mean(),
        frame["mw_q0.50"].mean(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
