"""Design-matrix transforms: multi-model spread, trajectory terms, calendar."""

import numpy as np
import pandas as pd
import pytest

from renewable_forecast.features import assemble


def _zonal(models: dict[str, list[float]], n: int = 4) -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    return pd.concat(
        [
            pd.DataFrame(
                {
                    "model": model,
                    "valid_time": times,
                    "power_curve": values,
                    "wind_speed_100m": np.array(values) * 10,
                }
            )
            for model, values in models.items()
        ],
        ignore_index=True,
    )


def test_multi_model_pivots_each_model_into_its_own_column() -> None:
    wide = assemble.multi_model(_zonal({"a": [0.1] * 4, "b": [0.3] * 4}))
    assert "power_curve__a" in wide.columns
    assert "power_curve__b" in wide.columns
    assert len(wide) == 4, "one row per valid time, not per model"


def test_cross_model_spread_is_zero_when_models_agree() -> None:
    wide = assemble.multi_model(_zonal({"a": [0.2] * 4, "b": [0.2] * 4}))
    assert (wide.power_curve_model_std == 0).all()
    assert (wide.power_curve_model_range == 0).all()
    assert wide.power_curve_model_mean.to_numpy() == pytest.approx(0.2)


def test_cross_model_spread_grows_with_disagreement() -> None:
    tight = assemble.multi_model(_zonal({"a": [0.2] * 4, "b": [0.25] * 4}))
    wide = assemble.multi_model(_zonal({"a": [0.05] * 4, "b": [0.60] * 4}))
    assert wide.power_curve_model_std.iloc[0] > tight.power_curve_model_std.iloc[0]


def test_spread_needs_at_least_two_models() -> None:
    single = assemble.multi_model(_zonal({"a": [0.2] * 4}))
    assert "power_curve_model_std" not in single.columns


def test_temporal_terms_capture_ramps_and_are_not_forward_filled() -> None:
    frame = pd.DataFrame({"x": [0.0, 1.0, 2.0, 5.0]})
    out = assemble.temporal(frame, ("x",))
    assert out["x_ramp1"].tolist()[1:] == [1.0, 1.0, 3.0]
    assert np.isnan(out["x_ramp1"].iloc[0]), "the first ramp is genuinely unknown"
    assert out["x_shift+1"].tolist()[1:] == [0.0, 1.0, 2.0]


def test_calendar_is_cyclical_and_carries_no_raw_datetime() -> None:
    times = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    out = assemble.calendar(pd.DataFrame({"valid_time": times}))
    assert set(out.columns) == {"hour_sin", "hour_cos", "doy_sin", "doy_cos"}
    # Midnight and the following midnight must map to the same point on the circle.
    day_later = assemble.calendar(
        pd.DataFrame({"valid_time": times + pd.Timedelta(days=1)})
    )
    assert out.hour_sin.iloc[0] == pytest.approx(day_later.hour_sin.iloc[0])
    unit_circle = (out.hour_sin**2 + out.hour_cos**2).to_numpy()
    assert unit_circle == pytest.approx(1.0)
