"""Price targets and features must obey native resolution and auction availability."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from grid_signals.forecast import windows
from grid_signals.forecast.models import price as models
from grid_signals.forecast.pipelines import price
from grid_signals.forecast.sources import prices


def test_old_hourly_prices_never_become_native_quarter_targets():
    hourly = pd.Series(
        10.0, index=pd.date_range("2025-09-30", periods=24, freq="h", tz="UTC")
    )
    quarters = pd.Series(
        20.0, index=pd.date_range("2025-10-01", periods=4, freq="15min", tz="UTC")
    )
    selected = prices.native(pd.concat([hourly, quarters]).sort_index())
    assert selected.index.tolist() == quarters.index.tolist()


def test_utc_lag_on_autumn_clock_change_cannot_use_the_unknown_delivery_auction():
    history = pd.Series(
        50.0, index=pd.date_range("2026-10-01", "2026-10-27", freq="15min", tz="UTC")
    )
    times = pd.DatetimeIndex(
        windows.delivery_day_starts(
            date(2026, 10, 25), resolution=timedelta(minutes=15)
        )
    )
    frame = prices.features(history, times)
    assert len(frame) == 100
    assert frame.p_lag_24.iloc[-4:].isna().all()
    assert frame.p_lag_168.notna().all()


def test_future_auction_prices_cannot_change_forecast_inputs():
    times = pd.date_range("2026-01-01", "2026-02-01", freq="15min", tz="UTC")
    history = pd.Series(np.arange(len(times), dtype=float), index=times)
    target = pd.DatetimeIndex(
        windows.delivery_day_starts(date(2026, 1, 25), resolution=timedelta(minutes=15))
    )
    before = prices.features(history, target)
    changed = history.copy()
    changed.loc[target] = 1e9
    after = prices.features(changed, target)
    columns = [
        column for column in before if column.startswith(("p_lag_", "profile_", "dow_"))
    ]
    pd.testing.assert_frame_equal(before[columns], after[columns])


def test_price_scores_preserve_eur_units_and_negative_values():
    truth = np.array([-50.0, 0.0, 100.0])
    quantiles = np.tile(truth[:, None], (1, 19)) + 10
    result = price.score(truth, quantiles)
    assert result["mae"] == pytest.approx(10)
    assert result["rmse"] == pytest.approx(10)
    assert result["bias"] == pytest.approx(10)


def test_price_gbm_does_not_inherit_generation_clipping(monkeypatch):
    monkeypatch.setitem(models.PARAMS, "n_estimators", 3)
    rows = pd.DataFrame(
        {
            "price": np.linspace(-100, -10, 200),
            "p_lag_24": np.linspace(-110, -20, 200),
            "quarter": np.arange(200) % 96,
        }
    )
    model = models.QuantileGBM().fit(rows)
    output = model.predict(rows)
    assert output.shape == (200, 19)
    assert (output < 0).all()
    assert (np.diff(output, axis=1) >= 0).all()
