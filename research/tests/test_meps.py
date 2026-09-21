"""Tests for the MEPS run-addressed NWP source.

Three things here are worth guarding, in descending order of how quietly they would
fail:

1. **Grid location.** An off-by-one in the projection maths moves a query point 2.5 km
   and nothing downstream complains. The expected indices are pinned against the
   archive's own published 2-D latitude/longitude arrays.
2. **Wind rotation.** MEPS stores grid-relative components. Forgetting the convergence
   rotation leaves direction wrong by up to a few degrees across SE3 -- small enough to
   look plausible, large enough to matter for a directional feature.
3. **Lead coverage.** The fetched window must contain the whole delivery day for every
   issue day, daylight saving included.

Tests that touch thredds.met.no are opt-in via `MEPS_NETWORK_TESTS=1`, so the default
suite stays hermetic.
"""

import os
from datetime import UTC, date, datetime

import numpy as np
import pytest

from renewable_forecast import windows
from renewable_forecast.sources import meps

NETWORK = pytest.mark.skipif(
    os.environ.get("MEPS_NETWORK_TESTS") != "1",
    reason="set MEPS_NETWORK_TESTS=1 to exercise the live archive",
)

#: Verified against the file's published `latitude`/`longitude` arrays by exhaustive
#: nearest-neighbour search. If the analytic projection ever disagrees with these, the
#: projection constants have drifted from the archive.
KNOWN_POINTS = [
    (57.8907, 14.7451, 292, 418),
    (60.5561, 16.4182, 411, 455),
    (57.3376, 18.0748, 269, 498),
    (58.7368, 11.6304, 332, 346),
]


@pytest.mark.parametrize(("lat", "lon", "j", "i"), KNOWN_POINTS)
def test_grid_index_matches_published_coordinates(
    lat: float, lon: float, j: int, i: int
) -> None:
    assert meps.grid_index(lat, lon) == (j, i)


def test_grid_index_stays_inside_the_domain() -> None:
    # Far outside MEPS, which covers the Nordics: must clamp, not index out of bounds.
    j, i = meps.grid_index(0.0, 0.0)
    assert 0 <= j < meps.GRID_NY
    assert 0 <= i < meps.GRID_NX


def test_convergence_vanishes_on_the_central_meridian() -> None:
    assert meps.grid_convergence(15.0) == pytest.approx(0.0)


def test_convergence_changes_sign_across_the_central_meridian() -> None:
    assert meps.grid_convergence(20.0) > 0
    assert meps.grid_convergence(10.0) < 0


def test_wind_speed_is_invariant_to_rotation() -> None:
    u = np.array([[3.0], [-4.0]])
    v = np.array([[4.0], [3.0]])
    west, _ = meps.wind_speed_direction(u, v, 5.0)
    east, _ = meps.wind_speed_direction(u, v, 25.0)
    assert west == pytest.approx(np.array([[5.0], [5.0]]))
    assert east == pytest.approx(np.array([[5.0], [5.0]]))


@pytest.mark.parametrize(
    ("u", "v", "expected"),
    [
        (0.0, -1.0, 0.0),  # blowing toward -y, i.e. from the north
        (-1.0, 0.0, 90.0),  # blowing toward -x, i.e. from the east
        (0.0, 1.0, 180.0),  # from the south
        (1.0, 0.0, 270.0),  # from the west
    ],
)
def test_wind_direction_uses_the_meteorological_convention(
    u: float, v: float, expected: float
) -> None:
    """On the central meridian grid north is true north, so no rotation applies."""
    _, direction = meps.wind_speed_direction(
        np.array([[u]]),
        np.array([[v]]),
        meps.PROJECTION["longitude_of_central_meridian"],
    )
    assert float(direction[0, 0]) == pytest.approx(expected, abs=1e-6)


def test_wind_direction_is_rotated_by_the_convergence() -> None:
    u, v = np.array([[0.0]]), np.array([[-1.0]])
    longitude = 20.0
    _, direction = meps.wind_speed_direction(u, v, longitude)
    assert float(direction[0, 0]) == pytest.approx(meps.grid_convergence(longitude))


@pytest.mark.parametrize(
    "issue_day",
    [
        date(2025, 1, 15),
        date(2025, 7, 15),
        date(2026, 3, 28),  # spring forward: 23-hour delivery day
        date(2026, 10, 24),  # autumn back: 25-hour delivery day
    ],
)
def test_fetched_leads_cover_the_whole_delivery_day(issue_day: date) -> None:
    covered = set(range(meps.LEAD_FIRST, meps.LEAD_LAST + 1))
    assert set(windows.lead_hours(issue_day)) <= covered


def test_lead_window_leaves_room_for_trajectory_features() -> None:
    """Rolling and shifted features reach outside the delivery day on both sides."""
    needed = windows.lead_hours(date(2025, 1, 15))
    assert min(needed) - 5 >= meps.LEAD_FIRST
    assert max(needed) + 3 <= meps.LEAD_LAST


def test_run_precedes_issue_time() -> None:
    """The defining property: a 00z run is knowable at the 09:00 UTC issue time."""
    issue_day = date(2025, 6, 1)
    run = datetime(
        issue_day.year, issue_day.month, issue_day.day, meps.RUN_HOUR_UTC, tzinfo=UTC
    )
    assert run < windows.issue_time(issue_day)


def test_runs_yields_daily_midnight_instants() -> None:
    generated = list(meps.runs(date(2025, 1, 1), date(2025, 1, 4)))
    assert generated == [
        datetime(2025, 1, 1, 0, tzinfo=UTC),
        datetime(2025, 1, 2, 0, tzinfo=UTC),
        datetime(2025, 1, 3, 0, tzinfo=UTC),
    ]


def test_run_url_addresses_a_named_run_not_a_day() -> None:
    url = meps.run_url(datetime(2025, 3, 4, 0, tzinfo=UTC))
    assert url.endswith("2025/03/04/meps_det_hl_20250304T00Z.ncml")


ASCII_FIXTURE = """Dataset {
    Grid {
     ARRAY:
        Float32 x_wind_z[time = 2][height = 2][y = 1][x = 1];
    } x_wind_z;
} meps;
---------------------------------------------
x_wind_z.x_wind_z[2][2][1][1]
[0][0][0], 1.5
[0][1][0], 2.5
[1][0][0], 3.5
[1][1][0], 4.5

x_wind_z.time[2]
1.7724672E9, 1.7724708E9

x_wind_z.height[2]
80.0, 120.0
"""


def test_parse_ascii_recovers_arrays_and_axes() -> None:
    parsed = meps.parse_ascii(ASCII_FIXTURE)
    assert parsed["x_wind_z.x_wind_z"].tolist() == [1.5, 2.5, 3.5, 4.5]
    assert parsed["x_wind_z.height"].tolist() == [80.0, 120.0]
    assert len(parsed["x_wind_z.time"]) == 2


def test_parse_ascii_rejects_an_error_page() -> None:
    with pytest.raises(ValueError, match="unexpected OPeNDAP response"):
        meps.parse_ascii("<html>500 Internal Server Error</html>")


@NETWORK
def test_bounding_box_matches_the_ascii_oracle() -> None:
    """The two decode paths must agree, or the box is being indexed wrongly."""
    import httpx

    from renewable_forecast.features import sites

    points = sites.build("SE3").head(2)
    run = datetime(2026, 3, 2, 0, tzinfo=UTC)
    box = meps.fetch_run(run, points)
    with httpx.Client(timeout=180.0, follow_redirects=True) as client:
        for point in points.itertuples():
            oracle = meps.fetch_point_ascii(client, run, point)
            merged = box.merge(
                oracle, on=["valid_time", "point_id", "height_m"], suffixes=("", "_ref")
            )
            assert len(merged) == len(oracle)
            for column in ("wind_speed", "wind_direction", "temperature_c"):
                assert merged[column].to_numpy() == pytest.approx(
                    merged[f"{column}_ref"].to_numpy(), abs=1e-4
                )


@NETWORK
def test_product_signature_is_unchanged_across_the_archive() -> None:
    """Era drift was the headline risk; this is the check that would catch it."""
    import xarray as xr

    for run in (
        datetime(2024, 3, 1, 0, tzinfo=UTC),
        datetime(2025, 6, 1, 0, tzinfo=UTC),
        datetime(2026, 2, 1, 0, tzinfo=UTC),
    ):
        with xr.open_dataset(meps.run_url(run), decode_timedelta=True) as dataset:
            assert dataset.sizes["x"] == meps.GRID_NX
            assert dataset.sizes["y"] == meps.GRID_NY
            assert tuple(dataset.height.values) == meps.HEIGHTS_M
            assert set(meps.VARIABLES) <= set(dataset.data_vars)
