"""Capacity-series construction from a turbine registry."""

from datetime import date

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from grid_signals.forecast.sources import fleet


def _turbines(rows) -> gpd.GeoDataFrame:
    frame = pd.DataFrame(rows)
    return gpd.GeoDataFrame(frame, geometry=[Point(16.0, 59.0)] * len(frame), crs=4326)


def test_capacity_accumulates_over_commissioning_dates() -> None:
    turbines = _turbines(
        [
            {
                "zone": "SE3",
                "offshore": False,
                "capacity_mw": 2.0,
                "commissioned": date(2020, 1, 1),
                "decommissioned": False,
                "last_updated": pd.NaT,
            },
            {
                "zone": "SE3",
                "offshore": False,
                "capacity_mw": 3.0,
                "commissioned": date(2022, 6, 1),
                "decommissioned": False,
                "last_updated": pd.NaT,
            },
        ]
    )
    series = fleet.capacity_series(turbines, "SE3")
    assert fleet.capacity_at(series, date(2021, 1, 1)) == 2.0
    assert fleet.capacity_at(series, date(2023, 1, 1)) == 5.0


def test_capacity_before_the_first_turbine_is_zero() -> None:
    turbines = _turbines(
        [
            {
                "zone": "SE3",
                "offshore": False,
                "capacity_mw": 2.0,
                "commissioned": date(2020, 1, 1),
                "decommissioned": False,
                "last_updated": pd.NaT,
            },
        ]
    )
    series = fleet.capacity_series(turbines, "SE3")
    assert fleet.capacity_at(series, date(2019, 1, 1)) == 0.0


def test_decommissioned_turbines_are_removed() -> None:
    turbines = _turbines(
        [
            {
                "zone": "SE3",
                "offshore": False,
                "capacity_mw": 2.0,
                "commissioned": date(2010, 1, 1),
                "decommissioned": True,
                "last_updated": pd.Timestamp("2021-01-01"),
            },
            {
                "zone": "SE3",
                "offshore": False,
                "capacity_mw": 5.0,
                "commissioned": date(2010, 1, 1),
                "decommissioned": False,
                "last_updated": pd.NaT,
            },
        ]
    )
    series = fleet.capacity_series(turbines, "SE3")
    assert fleet.capacity_at(series, date(2020, 1, 1)) == 7.0
    assert fleet.capacity_at(series, date(2022, 1, 1)) == 5.0


def test_zones_and_placements_do_not_leak_into_each_other() -> None:
    turbines = _turbines(
        [
            {
                "zone": "SE3",
                "offshore": False,
                "capacity_mw": 2.0,
                "commissioned": date(2020, 1, 1),
                "decommissioned": False,
                "last_updated": pd.NaT,
            },
            {
                "zone": "SE4",
                "offshore": False,
                "capacity_mw": 9.0,
                "commissioned": date(2020, 1, 1),
                "decommissioned": False,
                "last_updated": pd.NaT,
            },
            {
                "zone": "SE3",
                "offshore": True,
                "capacity_mw": 30.0,
                "commissioned": date(2020, 1, 1),
                "decommissioned": False,
                "last_updated": pd.NaT,
            },
        ]
    )
    onshore = fleet.capacity_series(turbines, "SE3")
    offshore = fleet.capacity_series(turbines, "SE3", offshore=True)
    assert fleet.capacity_at(onshore, date(2021, 1, 1)) == 2.0
    assert fleet.capacity_at(offshore, date(2021, 1, 1)) == 30.0
