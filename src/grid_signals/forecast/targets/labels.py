"""Assemble the modelling target: hourly capacity factor with quality flags."""

import logging

import pandas as pd

from grid_signals.forecast import paths
from grid_signals.forecast.sources import entsoe, fleet
from grid_signals.forecast.targets import actuals, capacity

logger = logging.getLogger(__name__)

#: Hours at or below this price are where curtailment becomes plausible.
NEGATIVE_PRICE_EUR = 0.0


def _prices(zone: str) -> pd.Series:
    """Day-ahead prices on the hourly UTC grid, or an empty series if not pulled."""
    raw = entsoe.load("day_ahead_prices", zone)
    if raw.empty:
        return pd.Series(dtype="float64")
    stamps = pd.to_datetime(raw.period_start, utc=True)
    return (
        raw.assign(hour=stamps.dt.floor("h"))
        .groupby("hour")["value_mw"]  # the price column reuses the generic value name
        .mean()
        .rename("price_eur_mwh")
    )


def build(
    zone: str = "SE3", fuel: str = "wind_onshore", resolution: str = "1h"
) -> pd.DataFrame:
    """Build the target table for one zone and fuel.

    Returns one row per hour with observed MW, the capacity denominator from both
    methods, the capacity factor, and the flags that decide what is trainable.
    """
    raw = entsoe.load("actual_generation", zone)
    if raw.empty:
        msg = f"no actual_generation cached for {zone}"
        raise RuntimeError(msg)
    raw["fuel_type"] = raw.fuel_type.map(actuals.slug)

    if resolution not in {"1h", "15min"}:
        raise ValueError("resolution must be 1h or 15min")
    hourly = (
        actuals.to_hourly(raw)
        if resolution == "1h"
        else actuals.to_quarter_hourly(raw).assign(
            n_sub=1, expected_sub=1, native_minutes=15
        )
    )
    hourly = hourly[hourly.fuel_type == fuel].sort_values("period_start")
    observed = hourly.set_index("period_start").mw

    turbines = fleet.load_turbines()
    registry = capacity.align(capacity.registry_series(turbines, zone), observed.index)
    estimated = capacity.align(capacity.observed_series(observed), observed.index)

    factor = (observed / registry).rename("cf")
    capacity.assert_flat_ceiling(factor.dropna())

    frame = pd.DataFrame(
        {
            "period_start": observed.index,
            "zone": zone,
            "fuel_type": fuel,
            "mw": observed.to_numpy(),
            "capacity_mw": registry.to_numpy(),
            "capacity_mw_observed": estimated.to_numpy(),
            "cf": factor.to_numpy(),
        }
    )
    frame["n_sub"] = hourly.n_sub.to_numpy()
    frame["native_minutes"] = hourly.native_minutes.to_numpy()

    frame["partial_hour"] = (hourly.n_sub < hourly.expected_sub).to_numpy()
    frame["capacity_disagreement"] = capacity.compare(
        pd.Series(registry.to_numpy()), pd.Series(estimated.to_numpy())
    ).to_numpy()
    frame["capacity_quarantine"] = (
        frame.capacity_disagreement > capacity.CAPACITY_AGREEMENT_TOL
    )

    price = _prices(zone)
    frame["price_eur_mwh"] = (
        frame.period_start.map(price) if not price.empty else float("nan")
    )
    # Curtailment is not observable. Flag where it is plausible, report metrics with and
    # without these hours, and model it only if the gap turns out to matter.
    frame["possible_curtailment"] = frame.price_eur_mwh <= NEGATIVE_PRICE_EUR

    frame["trainable"] = (
        frame.cf.notna() & ~frame.partial_hour & frame.cf.between(-0.01, 1.05)
    )
    return frame


def write(
    zone: str = "SE3", fuel: str = "wind_onshore", resolution: str = "1h"
) -> pd.DataFrame:
    """Build the target table and persist it to the interim store."""
    frame = build(zone, fuel, resolution)
    paths.INTERIM.mkdir(parents=True, exist_ok=True)
    suffix = "_15min" if resolution == "15min" else ""
    out = paths.INTERIM / f"targets_{zone.lower()}_{fuel}{suffix}.parquet"
    frame.to_parquet(out, index=False)
    logger.info(
        "wrote %s (%s rows, %.1f%% trainable)",
        out,
        len(frame),
        100 * frame.trainable.mean(),
    )
    return frame
