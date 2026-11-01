"""Portable scores and native observation projection preserve research semantics."""

import numpy as np
import pandas as pd
import pytest
import scoringrules as sr

from grid_signals.forecast.reporting.export_explorer import (
    LEVELS,
    expand_native,
    normalise_backtest,
)
from grid_signals.forecast.sources.market_context import normalise_generation


def test_native_hour_projection_keeps_gaps_and_does_not_overlap_new_quarters():
    index = pd.to_datetime(
        [
            "2026-09-01T00:00Z",
            "2026-09-01T01:00Z",
            "2026-09-01T02:00Z",
            "2026-09-01T04:00Z",
            "2026-09-01T04:15Z",
        ]
    )
    series = pd.Series([10.0, 20.0, 25.0, 30.0, 40.0], index=index)
    expanded = expand_native(series)
    assert expanded.index.is_unique
    assert expanded.loc["2026-09-01T00:45Z", "value"] == 10
    assert pd.Timestamp("2026-09-01T03:00Z") not in expanded.index
    assert expanded.loc["2026-09-01T04:15Z", "value"] == 40


def test_export_uses_all_nineteen_quantiles_and_consistent_signed_bias():
    actual = np.array([0.4, 0.6])
    quantiles = np.tile(LEVELS, (2, 1))
    source = pd.DataFrame(
        {
            "valid_time": pd.date_range("2026-09-01T00:00Z", periods=2, freq="15min"),
            "delivery_day": pd.Timestamp("2026-09-01"),
            "cf": actual,
            "capacity_mw": [100, 200],
            "forecaster": "quantile",
            "daylight": [False, True],
        }
    )
    for index, level in enumerate(LEVELS):
        source[f"q{level:.2f}"] = quantiles[:, index]
    result = normalise_backtest(source, "solar", "Final holdout")
    np.testing.assert_allclose(
        result.crps, sr.crps_quantile(actual, quantiles, LEVELS) * [100, 200]
    )
    np.testing.assert_allclose(result.bias, [10, -20])
    assert result.eligible.tolist() == [False, True]
    assert result.model.tolist() == ["solar_quantile", "solar_quantile"]
    assert len([column for column in result if column.startswith("q0.")]) == 7
    assert result.actual.tolist() == [40, 120]


def test_export_rejects_crossing_or_duplicate_evaluated_intervals():
    frame = pd.DataFrame(
        {
            "valid_time": [pd.Timestamp("2026-09-01T00:00Z")] * 2,
            "delivery_day": pd.Timestamp("2026-09-01"),
            "price": 50,
            "forecaster": "lear_hourly",
        }
    )
    for level in LEVELS:
        frame[f"q{level:.2f}"] = level * 100
    with pytest.raises(ValueError, match="duplicate"):
        normalise_backtest(frame, "price", "Final holdout")
    frame = frame.iloc[:1].copy()
    frame["q0.05"] = 200
    with pytest.raises(ValueError, match="crossing"):
        normalise_backtest(frame, "price", "Final holdout")


def test_generation_keeps_unreported_offshore_missing_and_excludes_consumption():
    raw = pd.DataFrame(
        {
            ("Wind Onshore", "Actual Aggregated"): [4.0],
            ("Wind Onshore", "Actual Consumption"): [8.0],
            ("Solar", "Actual Aggregated"): [2.0],
        },
        index=[pd.Timestamp("2026-09-01T00:00Z")],
    )
    result = normalise_generation(raw)
    assert result.wind_onshore.iloc[0] == 4
    assert result.solar.iloc[0] == 2
    assert "wind_offshore" not in result
