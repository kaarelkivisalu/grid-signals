"""The capacity denominator, and the diagnostic that says whether it is right.

A wrong denominator is the most insidious error in this project: it injects a smooth
trend that the model learns as seasonality, and every capacity-factor metric becomes
uninterpretable while still looking reasonable.
"""

import logging

import pandas as pd

from grid_signals.forecast.sources import fleet

logger = logging.getLogger(__name__)

#: Scaling constant for the observation-derived capacity estimate. Its exact value
#: only sets a constant offset, which `compare` normalises away.
MAX_PLAUSIBLE_CF = 0.95

#: Registry and observation-derived capacity must agree this closely.
CAPACITY_AGREEMENT_TOL = 0.15

#: The ceiling diagnostic uses a high quantile, never the maximum -- a single metering
#: spike or a late registry entry is enough to push the maximum above 1.0.
CEILING_QUANTILE = 0.999


def registry_series(turbines, zone: str, *, offshore: bool = False) -> pd.DataFrame:
    """Daily installed capacity from commissioning dates."""
    return fleet.capacity_series(turbines, zone, offshore=offshore)


def observed_series(hourly_mw: pd.Series, window_days: int = 365) -> pd.DataFrame:
    """A second, independent capacity estimate derived from generation alone.

    Trailing high-percentile output divided by the maximum plausible capacity factor.
    It lags real capacity growth by up to a year, so it is a cross-check rather than a
    replacement -- but it depends on nothing the registry could get wrong.
    """
    daily_peak = hourly_mw.resample("D").max()
    rolling = daily_peak.rolling(f"{window_days}D", min_periods=30).quantile(0.995)
    estimate = (rolling / MAX_PLAUSIBLE_CF).rename("capacity_mw")
    frame = estimate.rename_axis("date").reset_index()
    # align() reindexes on tz-naive normalised dates; keeping tz here silently matched
    # nothing and left the cross-check entirely NaN.
    frame["date"] = frame.date.dt.tz_localize(None)
    return frame


def align(series: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Broadcast a daily capacity series onto an hourly UTC index."""
    daily = series.set_index("date").capacity_mw
    return pd.Series(
        daily.reindex(index.tz_localize(None).normalize()).ffill().to_numpy(),
        index=index,
        name="capacity_mw",
    )


def ceiling_by_year(capacity_factor: pd.Series) -> pd.Series:
    """Yearly high-quantile capacity factor -- flat means the denominator is right."""
    return capacity_factor.groupby(capacity_factor.index.year).quantile(
        CEILING_QUANTILE
    )


def assert_flat_ceiling(
    capacity_factor: pd.Series, lo: float = 0.70, hi: float = 1.00
) -> pd.Series:
    """Raise if the implied ceiling leaves the plausible band in any complete year.

    Called from the dataset build so a capacity regression fails loudly rather than
    quietly becoming a learned trend.
    """
    ceiling = ceiling_by_year(capacity_factor)
    complete = ceiling.iloc[1:-1]  # first and last years are partial
    bad = complete[(complete < lo) | (complete > hi)]
    if not bad.empty:
        msg = f"implied CF ceiling outside [{lo}, {hi}] in {bad.to_dict()}"
        raise ValueError(msg)
    return ceiling


def compare(registry: pd.Series, observed: pd.Series) -> pd.Series:
    """Disagreement between the two capacity estimates, net of their constant offset.

    The observation-derived estimate is biased by however far `MAX_PLAUSIBLE_CF` sits
    from the fleet's real ceiling, which for SE3 is roughly 13%. That offset is expected
    and harmless. What matters is whether it *changes* -- a registry that missed a
    commissioning shows up as a step in the ratio, not as a level difference. So the
    ratio is normalised by its own median before being compared to tolerance.
    """
    ratio = registry / observed
    return (ratio / ratio.median() - 1).abs()
