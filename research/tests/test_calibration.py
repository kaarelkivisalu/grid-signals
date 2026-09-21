"""Calibration split and conformal correction.

The bug these guard against is subtle and severe: estimating a model's residual spread
on the data it was fitted to gives intervals that are far too narrow, and the more
capacity the model has the worse it gets. The first run of the leaderboard showed 33%
coverage at a nominal 80% for the boosted point model.
"""

import numpy as np
import pandas as pd
import pytest

from renewable_forecast.evaluation import metrics, splits
from renewable_forecast.models.conformal import SpreadCQR, StratifiedCQR

LEVELS = np.round(np.arange(0.05, 1.0, 0.05), 2)


def _train(n_days: int = 100) -> pd.DataFrame:
    days = pd.date_range("2025-01-01", periods=n_days, freq="D")
    rows = pd.DataFrame(
        {
            "delivery_day": np.repeat(days, 24),
            "lead_hour": np.tile(np.arange(24) + 22, n_days),
        }
    )
    rng = np.random.default_rng(0)
    rows["cf"] = rng.uniform(0, 1, len(rows))
    return rows


def test_calibration_split_reserves_the_most_recent_days() -> None:
    train = _train()
    inner, calib = splits.calibration_split(train, fraction=0.25)
    assert inner.delivery_day.max() < calib.delivery_day.min()
    assert len(inner) + len(calib) == len(train)


def test_calibration_split_never_splits_a_day_across_both_sides() -> None:
    inner, calib = splits.calibration_split(_train(), fraction=0.25)
    assert not set(inner.delivery_day) & set(calib.delivery_day)


def test_calibration_split_degrades_gracefully_on_short_windows() -> None:
    """With too few days there is nothing to hold out; return the window unchanged."""
    short = _train(n_days=10)
    inner, calib = splits.calibration_split(short)
    assert len(inner) == len(short)
    assert len(calib) == len(short)


def test_in_sample_residuals_understate_spread() -> None:
    """The defect itself, reproduced: it is why the split exists."""
    rng = np.random.default_rng(1)
    train = _train()
    # A "model" that memorises training data perfectly but is useless out of sample.
    in_sample_residuals = np.zeros(len(train))
    out_of_sample_residuals = rng.normal(0, 0.2, len(train))
    assert np.std(in_sample_residuals) < np.std(out_of_sample_residuals)

    point = np.full(len(train), 0.5)
    narrow = point[:, None] + np.quantile(in_sample_residuals, LEVELS)[None, :]
    actual = 0.5 + out_of_sample_residuals
    assert metrics.coverage(actual, narrow, LEVELS, 0.80) < 0.1


def test_conformal_widens_underdispersed_intervals() -> None:
    rng = np.random.default_rng(2)
    calib = _train(60)
    actual = rng.normal(0.4, 0.2, len(calib)).clip(0, 1)
    calib = calib.assign(cf=actual).reset_index(drop=True)

    # Intervals deliberately far too narrow.
    squeezed = np.quantile(actual, LEVELS)[None, :].repeat(len(calib), axis=0)
    squeezed = 0.4 + (squeezed - 0.4) * 0.2

    before = metrics.coverage(actual, squeezed, LEVELS, 0.80)
    corrected = StratifiedCQR(LEVELS).fit(calib, squeezed).apply(calib, squeezed)
    after = metrics.coverage(actual, corrected, LEVELS, 0.80)

    assert before < 0.4, "the fixture must start underdispersed"
    assert after > before, "conformal correction must widen the interval"
    assert after == pytest.approx(0.80, abs=0.08)


def test_conformal_output_never_crosses_or_leaves_the_unit_interval() -> None:
    rng = np.random.default_rng(3)
    calib = _train(60).reset_index(drop=True)
    quantiles = np.sort(rng.uniform(0, 1, (len(calib), len(LEVELS))), axis=1)
    out = StratifiedCQR(LEVELS).fit(calib, quantiles).apply(calib, quantiles)
    assert (np.diff(out, axis=1) >= 0).all(), "quantiles must not cross"
    assert out.min() >= 0.0
    assert out.max() <= 1.0


def _heteroscedastic(n_days: int, seed: int) -> tuple[pd.DataFrame, np.ndarray]:
    """Rows whose error scale is set by a spread column, with identical raw intervals.

    The raw quantiles know nothing about the spread, which is the situation measured on
    SE3: the booster's intervals barely respond to model disagreement.
    """
    rng = np.random.default_rng(seed)
    frame = _train(n_days).reset_index(drop=True)
    spread = rng.uniform(0.0, 1.0, len(frame))
    frame["power_curve_model_std"] = spread
    frame["cf"] = (0.4 + rng.normal(0, 0.03 + 0.12 * spread)).clip(0, 1)
    raw = 0.4 + np.quantile(rng.normal(0, 0.05, 10_000), LEVELS)
    return frame, np.repeat(raw[None, :], len(frame), axis=0)


def test_spread_conformal_restores_coverage_where_the_models_disagree() -> None:
    calib, raw = _heteroscedastic(60, seed=4)
    test, raw_test = _heteroscedastic(60, seed=5)
    corrected = SpreadCQR(LEVELS).fit(calib, raw).apply(test, raw_test)

    disagree = test.power_curve_model_std.to_numpy() > 2 / 3
    agree = test.power_curve_model_std.to_numpy() < 1 / 3
    actual = test.cf.to_numpy()
    for rows in (disagree, agree):
        assert metrics.coverage(
            actual[rows], corrected[rows], LEVELS, 0.80
        ) == pytest.approx(0.80, abs=0.06)
    width = corrected[:, -1] - corrected[:, 0]
    assert width[disagree].mean() > 2 * width[agree].mean(), (
        "intervals must be wider where the NWP models disagree"
    )


def test_stratified_conformal_cannot_see_spread() -> None:
    """The defect SpreadCQR fixes: lead-and-level strata miss the spread signal."""
    calib, raw = _heteroscedastic(60, seed=4)
    test, raw_test = _heteroscedastic(60, seed=5)
    corrected = StratifiedCQR(LEVELS).fit(calib, raw).apply(test, raw_test)
    disagree = test.power_curve_model_std.to_numpy() > 2 / 3
    assert metrics.coverage(
        test.cf.to_numpy()[disagree], corrected[disagree], LEVELS, 0.80
    ) < 0.72


def test_spread_conformal_survives_a_missing_spread_column() -> None:
    calib, raw = _heteroscedastic(30, seed=6)
    calib = calib.drop(columns="power_curve_model_std")
    out = SpreadCQR(LEVELS).fit(calib, raw).apply(calib, raw)
    assert (np.diff(out, axis=1) >= 0).all()
    assert out.min() >= 0.0
    assert out.max() <= 1.0
