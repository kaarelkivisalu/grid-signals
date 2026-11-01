"""Normalisation of raw ENTSO-E rows onto the canonical hourly UTC grid."""

import pandas as pd

from grid_signals.forecast.targets import actuals


def _raw(timestamps, values, *, aggregation="Actual Aggregated"):
    return pd.DataFrame(
        {
            "period_start": pd.to_datetime(timestamps, utc=True),
            "fuel_type": "Wind Onshore",
            "aggregation": aggregation,
            "value_mw": values,
            "zone": "SE3",
            "fetched_at": pd.Timestamp("2026-01-01", tz="UTC"),
        }
    )


def test_slug_maps_known_and_unknown_names() -> None:
    assert actuals.slug("Wind Onshore") == "wind_onshore"
    assert actuals.slug("Hydro Water Reservoir") == "hydro_reservoir"
    assert actuals.slug("Some New Type") == "some_new_type"


def test_hourly_data_passes_through_unchanged() -> None:
    stamps = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    out = actuals.to_hourly(_raw(stamps, [100.0, 200.0, 300.0]))
    assert out.mw.tolist() == [100.0, 200.0, 300.0]
    assert out.n_sub.tolist() == [1, 1, 1]
    assert out.native_minutes.unique().tolist() == [60.0]


def test_quarter_hourly_is_averaged_into_whole_hours() -> None:
    stamps = pd.date_range("2026-01-01", periods=8, freq="15min", tz="UTC")
    out = actuals.to_hourly(_raw(stamps, [100, 200, 300, 400, 10, 20, 30, 40]))
    assert out.mw.tolist() == [250.0, 25.0]
    assert out.n_sub.tolist() == [4, 4]
    assert out.native_minutes.unique().tolist() == [15.0]


def test_partial_hours_are_flagged_by_n_sub() -> None:
    stamps = pd.date_range("2026-01-01", periods=6, freq="15min", tz="UTC")
    out = actuals.to_hourly(_raw(stamps, [100, 100, 100, 100, 50, 50]))
    assert out.n_sub.tolist() == [4, 2], "the incomplete hour must be distinguishable"


def test_actual_consumption_rows_are_dropped() -> None:
    stamps = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    mixed = pd.concat(
        [
            _raw(stamps, [100.0, 200.0]),
            _raw(stamps, [5.0, 5.0], aggregation="Actual Consumption"),
        ]
    )
    out = actuals.to_hourly(mixed)
    assert out.mw.tolist() == [100.0, 200.0]


def test_overlapping_chunks_keep_the_latest_fetch() -> None:
    stamps = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    old = _raw(stamps, [100.0, 200.0])
    new = _raw(stamps, [111.0, 222.0])
    new["fetched_at"] = pd.Timestamp("2026-02-01", tz="UTC")
    out = actuals.to_hourly(pd.concat([old, new]))
    assert out.mw.tolist() == [111.0, 222.0]
