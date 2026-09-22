"""Backtest geometry. The resampling unit is the delivery day, never the hour.

Adjacent hours within a day are ~0.95 correlated, so treating hours as independent
inflates the effective sample size by ~24x and makes every confidence interval a lie.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Split:
    """One rolling-origin fold, expressed as delivery days."""

    origin: date
    train_days: pd.DatetimeIndex
    test_days: pd.DatetimeIndex

    def __repr__(self) -> str:
        """Render the fold compactly for logs and leaderboards."""
        return (
            f"Split(origin={self.origin}, train={len(self.train_days)}d, "
            f"test={len(self.test_days)}d)"
        )


def seal_holdout(
    days: pd.DatetimeIndex, holdout_months: int = 6
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Split off the most recent months, to be opened exactly once.

    Returns (development, holdout). Every model-selection decision is made on the
    development set; the holdout exists to produce one honest headline number.
    """
    cutoff = days.max() - pd.DateOffset(months=holdout_months)
    return days[days <= cutoff], days[days > cutoff]


def rolling_origin(
    days: pd.DatetimeIndex,
    embargo_days: int = 7,
    origin_freq: str = "MS",
    min_train_days: int = 365,
) -> list[Split]:
    """Expanding-window folds with an embargo between train and test.

    The embargo kills autocorrelation bleed across the boundary and gives the capacity
    series time to stop mattering.
    """
    days = pd.DatetimeIndex(sorted(days))
    origins = pd.date_range(days.min(), days.max(), freq=origin_freq)
    splits = []
    for i, origin in enumerate(origins[:-1]):
        train_end = origin - timedelta(days=embargo_days)
        train = days[days <= train_end]
        test = days[(days > origin) & (days <= origins[i + 1])]
        if len(train) < min_train_days or test.empty:
            continue
        splits.append(Split(origin.date(), train, test))
    return splits


def day_block_bootstrap(
    values: pd.Series, days: pd.Series, n: int = 2000, seed: int = 0
) -> np.ndarray:
    """Resample whole delivery days with replacement and return the means.

    Used for confidence intervals on the *difference* between two models' losses.
    """
    rng = np.random.default_rng(seed)
    by_day = pd.DataFrame({"day": days.to_numpy(), "value": values.to_numpy()})
    grouped = by_day.groupby("day").value.mean()
    unique = grouped.to_numpy()
    draws = rng.integers(0, len(unique), size=(n, len(unique)))
    return unique[draws].mean(axis=1)


def bootstrap_ci(
    values: pd.Series, days: pd.Series, alpha: float = 0.05, **kwargs
) -> tuple[float, float]:
    """Percentile confidence interval from the day-block bootstrap."""
    draws = day_block_bootstrap(values, days, **kwargs)
    return float(np.quantile(draws, alpha / 2)), float(
        np.quantile(draws, 1 - alpha / 2)
    )


def calibration_split(
    train: pd.DataFrame, fraction: float = 0.25, day_column: str = "delivery_day"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reserve the most recent part of a training window for estimating spread.

    Residual distributions and conformal corrections must be estimated on data the
    model did not fit, or the intervals inherit the in-sample residuals -- which are
    systematically too small, and the more capacity the model has the worse it gets.
    Split by whole delivery days, like everything else here.
    """
    days = pd.DatetimeIndex(sorted(train[day_column].unique()))
    if len(days) < 30:
        return train, train
    cut = days[int(len(days) * (1 - fraction))]
    return train[train[day_column] < cut], train[train[day_column] >= cut]


def day_blocks(
    frame: pd.DataFrame, k: int = 4, day_column: str = "delivery_day"
) -> list[pd.Index]:
    """Row indices of `k` contiguous blocks of whole delivery days, oldest first.

    Contiguous rather than shuffled, so within-day and multi-day error correlation
    stays inside a block and out-of-fold residuals are honestly out of sample.
    """
    days = pd.DatetimeIndex(sorted(frame[day_column].unique()))
    edges = np.linspace(0, len(days), k + 1).round().astype(int)
    return [
        frame.index[frame[day_column].isin(days[lo:hi])]
        for lo, hi in zip(edges[:-1], edges[1:], strict=True)
    ]
