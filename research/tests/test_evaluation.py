"""Scoring identities and backtest geometry.

The metric tests are identities rather than regression values: pinball at the median is
exactly half the MAE, and the CRPS of a degenerate forecast is exactly the MAE. If those
break, the scoring is wrong no matter what the leaderboard says.
"""

import numpy as np
import pandas as pd
import pytest

from renewable_forecast.evaluation import metrics, splits

LEVELS = np.round(np.arange(0.05, 1.0, 0.05), 2)


@pytest.fixture
def calibrated() -> tuple[np.ndarray, np.ndarray]:
    """A climatological forecast that is calibrated by construction."""
    rng = np.random.default_rng(0)
    actual = rng.normal(0.3, 0.15, 20000).clip(0, 1)
    quantiles = np.quantile(actual, LEVELS)[None, :].repeat(len(actual), axis=0)
    return actual, quantiles


def test_pinball_at_the_median_is_half_the_mae(calibrated) -> None:
    actual, quantiles = calibrated
    median_idx = int(np.argmin(np.abs(LEVELS - 0.5)))
    pinball = metrics.pinball(actual, quantiles, LEVELS)[median_idx]
    assert pinball * 2 == pytest.approx(
        metrics.nmae(actual, quantiles[:, median_idx]), rel=1e-9
    )


def test_crps_of_a_point_forecast_equals_the_mae() -> None:
    actual = np.array([0.1, 0.5, 0.9])
    point = np.array([0.2, 0.4, 0.4])
    degenerate = point[:, None].repeat(len(LEVELS), axis=1)
    assert metrics.crps(actual, degenerate, LEVELS) == pytest.approx(
        metrics.nmae(actual, point), rel=1e-6
    )


def test_a_calibrated_forecast_has_nominal_coverage(calibrated) -> None:
    actual, quantiles = calibrated
    assert metrics.coverage(actual, quantiles, LEVELS, 0.80) == pytest.approx(
        0.80, abs=0.01
    )
    assert metrics.coverage(actual, quantiles, LEVELS, 0.90) == pytest.approx(
        0.90, abs=0.01
    )


def test_pit_is_uniform_when_calibrated(calibrated) -> None:
    """For a calibrated forecast, P(PIT <= q) == q at every level.

    Tested against the levels directly rather than through a histogram: 19 discrete
    levels do not divide evenly into histogram bins, so bin counts come out uneven even
    when the forecast is perfectly calibrated.
    """
    actual, quantiles = calibrated
    values = metrics.pit(actual, quantiles, LEVELS)
    for level in LEVELS:
        assert float(np.mean(values <= level)) == pytest.approx(level, abs=0.02)


def test_pit_detects_underdispersion(calibrated) -> None:
    """Too-narrow intervals push observations into the PIT tails."""
    actual, quantiles = calibrated
    squeezed = 0.3 + (quantiles - 0.3) * 0.25
    values = metrics.pit(actual, squeezed, LEVELS)
    edge_share = float(np.mean((values <= LEVELS[0]) | (values >= LEVELS[-1])))
    assert edge_share > 0.30, "underdispersion must push mass into the PIT tails"


def test_skill_score_sign_and_zero_point() -> None:
    assert metrics.skill_score(0.5, 1.0) == pytest.approx(0.5)
    assert metrics.skill_score(1.0, 1.0) == 0.0
    assert metrics.skill_score(2.0, 1.0) == pytest.approx(-1.0)


def test_holdout_is_sealed_off_the_end() -> None:
    days = pd.date_range("2020-01-01", "2026-09-19", freq="D")
    development, holdout = splits.seal_holdout(days, holdout_months=6)
    assert development.max() < holdout.min()
    assert len(development) + len(holdout) == len(days)
    assert holdout.min() >= days.max() - pd.DateOffset(months=6)


def test_folds_respect_the_embargo_and_never_look_ahead() -> None:
    days = pd.date_range("2020-01-01", "2026-03-19", freq="D")
    folds = splits.rolling_origin(days, embargo_days=7)
    assert folds, "expected at least one fold"
    for fold in folds:
        assert fold.train_days.max() < fold.test_days.min()
        gap = (fold.test_days.min() - fold.train_days.max()).days
        assert gap >= 7, f"embargo violated at origin {fold.origin}"


def test_training_windows_expand_monotonically() -> None:
    days = pd.date_range("2020-01-01", "2026-03-19", freq="D")
    sizes = [len(f.train_days) for f in splits.rolling_origin(days)]
    assert sizes == sorted(sizes)


def test_bootstrap_resamples_whole_days_not_hours() -> None:
    # Two days with wildly different losses; resampling hours would shrink the interval
    # far below what day-level resampling gives.
    hours = pd.date_range("2026-01-01", periods=48, freq="h")
    values = pd.Series([0.0] * 24 + [1.0] * 24)
    lo, hi = splits.bootstrap_ci(values, pd.Series(hours.normalize()), n=2000)
    assert lo == pytest.approx(0.0, abs=1e-9)
    assert hi == pytest.approx(1.0, abs=1e-9)
