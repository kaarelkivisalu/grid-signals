"""The forward baseline requires complete known curves, including 23/25-hour days."""

from datetime import date, timedelta

import pandas as pd
import pytest

from renewable_forecast import windows
from renewable_forecast.pipelines.price_forward import profiles_available


@pytest.mark.parametrize("delivery", [date(2026, 3, 30), date(2026, 10, 26)])
def test_previous_dst_day_is_a_complete_price_profile(delivery):
    times = []
    for lag in [1, 2, 3, 7]:
        times.extend(
            windows.delivery_day_starts(
                delivery - timedelta(days=lag), resolution=timedelta(minutes=15)
            )
        )
    history = pd.Series(50.0, index=pd.DatetimeIndex(times).sort_values())
    assert profiles_available(history, delivery)
    assert not profiles_available(history.iloc[:-1], delivery)
