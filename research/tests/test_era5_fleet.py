import numpy as np
import pandas as pd
import pytest
import xarray as xr

from grid_signals.forecast.features import era5_fleet


def test_low_specific_power_reaches_rated_at_lower_speed():
    speeds = np.linspace(0, 20, 201)
    low = era5_fleet.specific_power_curve(speeds, np.full_like(speeds, 250.0))
    high = era5_fleet.specific_power_curve(speeds, np.full_like(speeds, 450.0))
    assert speeds[np.argmax(low >= 1.0)] < speeds[np.argmax(high >= 1.0)]
    assert (low >= high).all()


def test_curve_respects_cut_in_and_cut_out():
    speeds = np.array([2.9, 26.0])
    assert (era5_fleet.specific_power_curve(speeds, np.full(2, 300.0)) == 0).all()


def test_smoothing_stays_in_unit_interval_and_softens_the_knee():
    speeds = np.linspace(0, 30, 301)
    specific = np.full_like(speeds, 300.0)
    smooth = era5_fleet.smoothed_curve(speeds, specific)
    sharp = era5_fleet.specific_power_curve(speeds, specific)
    assert smooth.min() >= 0
    assert smooth.max() <= 1
    rated = np.argmax(sharp >= 1.0)
    assert smooth[rated] < 1.0


def test_hourly_intervals_average_bounding_instants():
    times = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    instants = pd.DataFrame(
        {
            "valid_time": times,
            "phys_smooth_mw": [0.0, 10.0, 20.0],
            "live_capacity_mw": [5.0, 5.0, 7.0],
        }
    )
    hourly = era5_fleet.to_hourly_intervals(instants)
    assert hourly.phys_smooth_mw.iloc[:2].tolist() == [5.0, 15.0]
    assert hourly.live_capacity_mw.iloc[2] == 7.0


def test_build_counts_a_turbine_only_after_commissioning():
    times = pd.date_range("2024-01-01", periods=4, freq="h")
    shape = (4, 2)
    dims = ("valid_time", "cell")
    grid = xr.Dataset(
        {
            "u100": (dims, np.full(shape, 8.0)),
            "v100": (dims, np.zeros(shape)),
            "u10": (dims, np.full(shape, 5.0)),
            "v10": (dims, np.zeros(shape)),
            "t2m": (dims, np.full(shape, 283.0)),
            "d2m": (dims, np.full(shape, 278.0)),
            "sp": (dims, np.full(shape, 101325.0)),
            "blh": (dims, np.full(shape, 500.0)),
        },
        coords={
            "valid_time": times,
            "latitude": ("cell", [59.0, 58.75]),
            "longitude": ("cell", [15.0, 15.25]),
        },
    )
    turbines = pd.DataFrame(
        {
            "latitude": [59.0, 58.75],
            "longitude": [15.0, 15.25],
            "capacity_mw": [3.0, 2.0],
            "hub_height_m": [100.0, 100.0],
            "specific_power": [300.0, 300.0],
            "commissioned": pd.to_datetime(
                ["2023-01-01 00:00", "2024-01-01 02:00"], utc=True
            ),
            "retired": pd.to_datetime([None, None], utc=True),
        }
    )
    clusters = pd.DataFrame({"latitude": [59.0], "longitude": [15.0]})
    out = era5_fleet.build(grid, turbines, clusters)
    assert out.live_capacity_mw.tolist() == [3.0, 3.0, 5.0, 5.0]
    per_mw = out.phys_smooth_mw / out.live_capacity_mw
    # Identical weather everywhere, so identical capacity factor whatever the fleet.
    assert per_mw.to_numpy() == pytest.approx(np.full(4, per_mw.iloc[0]))
    assert out.c0_cf.iloc[0] == pytest.approx(per_mw.iloc[0])
