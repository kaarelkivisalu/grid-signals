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

import logging
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from renewable_forecast import config, experiment, paths, windows
from renewable_forecast.features import assemble, sites
from renewable_forecast.models.quantile import QuantileGBM
from renewable_forecast.sources import ifs_runs, meps, openmeteo

logger = logging.getLogger(__name__)

#: Forecast vintages are append-only. A row is never edited once written; a re-run of
#: the same issue day appends a new vintage and the newest one wins on read.
VINTAGES = paths.PREDICTIONS / "forecast_vintages.parquet"

#: Extra days of NWP to refresh either side of the delivery day, so the temporal
#: features (lags and ramps) have neighbours to work with at the window edges.
CONTEXT_DAYS = 1


def refresh_nwp(
    delivery_day: date, zone: str = "SE3", run_addressed: tuple[str, ...] = ()
) -> None:
    """Pull the newest NWP covering the delivery day, merging into the archive.

    Run-addressed sources are fetched for the issue day's 00z run only. Each call also
    self-archives that run, which matters for MEPS: MET Norway's thredds archive now
    serves only the current month (checked 2026-09-22), so a run not saved on its day
    may not be recoverable later.
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
) -> pd.DataFrame:
    """Forecast one delivery day and append the vintage. Defaults to tomorrow."""
    delivery_day = delivery_day or (datetime.now(UTC).date() + timedelta(days=1))
    issue_day = delivery_day - timedelta(days=1)
    issued = windows.issue_time(issue_day)
    cfg = config.load()
    levels = np.array(cfg.task.quantiles)

    run_addressed = tuple(cfg.features.get("run_addressed", ()))
    flags = assemble.run_flags(run_addressed)
    if refresh:
        refresh_nwp(delivery_day, zone, run_addressed)

    train = assemble.build(zone, fuel, **flags)
    train = train[train.delivery_day < pd.Timestamp(delivery_day)]
    train = assemble.require_run_coverage(train, run_addressed)
    logger.info(
        "fitting on %s rows up to %s", len(train), train.delivery_day.max().date()
    )

    model = QuantileGBM(levels, **cfg.model.get("quantile", {})).fit(train)
    future = assemble.build_operational(delivery_day, zone, fuel, **flags)
    for source in run_addressed:
        column = assemble.RUN_SOURCES[source]
        if future[column].isna().any():
            # Refuse rather than silently forecast from a model fitted with a source
            # the live row lacks: the trees would route every hour down their
            # missing-value branches, which the backtest never scored.
            msg = f"{source} run for {issue_day} is missing; cannot forecast"
            raise RuntimeError(msg)
    quantiles = model.predict(future)

    out = future[["valid_time", "delivery_day", "lead_hour", "capacity_mw"]].copy()
    out["issue_time"] = issued
    out["model_version"] = experiment.version(cfg)
    out["created_at"] = datetime.now(UTC)
    for level, column in zip(levels, quantiles.T, strict=True):
        out[f"cf_q{level:.2f}"] = column
        out[f"mw_q{level:.2f}"] = column * out.capacity_mw

    paths.PREDICTIONS.mkdir(parents=True, exist_ok=True)
    if VINTAGES.exists():
        out = pd.concat([pd.read_parquet(VINTAGES), out], ignore_index=True)
    out.to_parquet(VINTAGES, index=False)
    logger.info("wrote %s rows to %s", len(out), VINTAGES)
    return out


def latest(zone: str = "SE3") -> pd.DataFrame:  # noqa: ARG001
    """The newest vintage on file, one row per delivery hour."""
    if not VINTAGES.exists():
        msg = f"{VINTAGES} does not exist; run predict first"
        raise FileNotFoundError(msg)
    frame = pd.read_parquet(VINTAGES)
    newest = frame.created_at.max()
    return frame[frame.created_at == newest].sort_values("valid_time")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    frame = run()
    logger.info(
        "%s: %.0f-%.0f MW (p10-p90), median %.0f MW",
        frame.delivery_day.iloc[0].date(),
        frame["mw_q0.10"].mean(),
        frame["mw_q0.90"].mean(),
        frame["mw_q0.50"].mean(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
