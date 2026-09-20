"""Wind physics and spatial aggregation.

The aggregation-order test is the important one: applying the power curve to a spatial
mean instead of per cluster is an easy mistake that silently makes the zonal forecast
too peaky, and no metric names it.
"""

import numpy as np
import pandas as pd
import pytest

from renewable_forecast.features import wind

RATED_SPEED = 12.0
CUT_IN = 3.0
CUT_OUT = 25.0


def test_power_curve_respects_cut_in_rated_and_cut_out() -> None:
    assert wind.power_curve(np.array([0.0, 2.9]))[1] == 0.0
    assert wind.power_curve(np.array([RATED_SPEED]))[0] == pytest.approx(1.0)
    assert wind.power_curve(np.array([20.0]))[0] == pytest.approx(1.0)
    assert wind.power_curve(np.array([CUT_OUT + 1]))[0] == 0.0


def test_power_curve_is_monotone_between_cut_in_and_rated() -> None:
    speeds = np.linspace(CUT_IN, RATED_SPEED, 50)
    output = wind.power_curve(speeds)
    assert np.all(np.diff(output) >= 0)


def test_air_density_falls_with_temperature_and_rises_with_pressure() -> None:
    cold = wind.air_density(np.array([-10.0]), np.array([1013.0]), np.array([80.0]))
    warm = wind.air_density(np.array([25.0]), np.array([1013.0]), np.array([80.0]))
    assert cold[0] > warm[0]

    low = wind.air_density(np.array([10.0]), np.array([980.0]), np.array([80.0]))
    high = wind.air_density(np.array([10.0]), np.array([1030.0]), np.array([80.0]))
    assert high[0] > low[0]

    # Standard conditions should land near the reference density.
    standard = wind.air_density(np.array([15.0]), np.array([1013.25]), np.array([0.0]))
    assert standard[0] == pytest.approx(wind.RHO_REFERENCE, abs=0.01)


def test_density_correction_boosts_cold_dense_air() -> None:
    dense = wind.density_corrected_speed(np.array([10.0]), np.array([1.35]))
    thin = wind.density_corrected_speed(np.array([10.0]), np.array([1.10]))
    assert dense[0] > 10.0 > thin[0]


def test_shear_extrapolation_increases_with_height() -> None:
    assert wind.extrapolate(np.array([5.0]), 100.0)[0] > 5.0
    assert wind.extrapolate(np.array([5.0]), 10.0)[0] == pytest.approx(5.0)


def _points(speeds: list[float]) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = len(speeds)
    points = pd.DataFrame(
        {
            "valid_time": pd.Timestamp("2026-01-01", tz="UTC"),
            "point_id": [f"p{i}" for i in range(n)],
            "model": "m",
            "power_curve": wind.power_curve(np.array(speeds)),
            "wind_speed_100m": speeds,
        }
    )
    weights = pd.DataFrame(
        {
            "point_id": [f"p{i}" for i in range(n)],
            "weight": [1 / n] * n,
        }
    )
    return points, weights


def test_aggregation_averages_power_not_speed() -> None:
    """Transform per cluster, then weight -- never transform the spatial mean.

    By Jensen's inequality the two orders differ wherever the curve is not linear, and
    they differ in *opposite* directions on either side of rated speed: below rated the
    curve is convex, so transforming the mean understates output; above rated it
    saturates, so transforming the mean overstates it. The second case is the one that
    matters for a zonal forecast, because it is what makes the naive order produce peaks
    the fleet cannot physically reach.
    """
    below_rated = [4.0, 10.0]
    points, weights = _points(below_rated)
    correct = wind.aggregate(points, weights).power_curve.iloc[0]
    naive = wind.power_curve(np.array([np.mean(below_rated)]))[0]
    assert correct == pytest.approx(np.mean(wind.power_curve(np.array(below_rated))))
    assert correct > naive, "convex region: transforming the mean understates"

    around_rated = [8.0, 20.0]
    points, weights = _points(around_rated)
    correct = wind.aggregate(points, weights).power_curve.iloc[0]
    naive = wind.power_curve(np.array([np.mean(around_rated)]))[0]
    assert correct < naive, "saturating region: transforming the mean overstates"


def test_aggregation_reports_spatial_dispersion() -> None:
    uniform, weights = _points([8.0, 8.0, 8.0])
    spread, spread_weights = _points([3.0, 8.0, 13.0])
    assert wind.aggregate(uniform, weights).wind_speed_100m_spatial_std.iloc[0] == 0.0
    assert (
        wind.aggregate(spread, spread_weights).wind_speed_100m_spatial_std.iloc[0] > 0
    )


def test_icing_memory_persists_after_conditions_clear() -> None:
    """Ice accretes and stays; an instantaneous flag alone would miss the aftermath."""
    frame = pd.DataFrame(
        {
            "point_id": "p0",
            "valid_time": pd.date_range("2026-01-01", periods=12, freq="h", tz="UTC"),
            "icing_now": [1.0] * 3 + [0.0] * 9,
        }
    )
    out = wind.add_icing_memory(frame)
    assert out.icing_6h.iloc[2] == 3.0
    assert out.icing_6h.iloc[5] == 3.0, "memory must survive the conditions clearing"
    assert out.icing_6h.iloc[11] == 0.0, "and must eventually decay"
    assert out.icing_24h.iloc[11] == 3.0
