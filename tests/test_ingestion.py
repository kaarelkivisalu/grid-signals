"""Tests for the ENTSO-E ingestion layer.

- Transformer tests: pure functions, no mocks
- Fuel type tests: mapping + fallback
- Integration tests: mocked client + in-memory DuckDB
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import duckdb
import numpy as np
import pandas as pd
import pytest
import requests.exceptions
from entsoe.exceptions import NoMatchingDataError

from grid_signals.db.queries import get_day_ahead_prices, get_outages
from grid_signals.db.schema import create_tables
from grid_signals.ingestion.client import BORDERS, ZONE_TO_ENTSOE
from grid_signals.ingestion.entsoe import (
    _retry_on_server_error,  # noqa: PLC2701
    ingest_cross_border_flows,
    ingest_day_ahead_prices,
    ingest_generation_per_type,
    ingest_outages,
    ingest_total_load,
)
from grid_signals.ingestion.fuel_types import FUEL_TYPE_MAP, normalize_fuel_type
from grid_signals.ingestion.transformers import (
    transform_cross_border_flows,
    transform_day_ahead_prices,
    transform_generation,
    transform_load,
    transform_outages,
)
from grid_signals.models import BiddingZone

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def con():
    """In-memory DuckDB with all tables created."""
    c = duckdb.connect(":memory:")
    create_tables(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Fuel type tests
# ---------------------------------------------------------------------------


class TestFuelTypes:
    def test_known_mappings(self):
        assert normalize_fuel_type("Fossil Oil shale") == "oil_shale"
        assert normalize_fuel_type("Wind Onshore") == "wind_onshore"
        assert normalize_fuel_type("Nuclear") == "nuclear"
        assert normalize_fuel_type("Solar") == "solar"

    def test_unknown_fallback(self):
        assert normalize_fuel_type("Some Future Type") == "some_future_type"

    def test_all_map_entries(self):
        for raw, slug in FUEL_TYPE_MAP.items():
            assert normalize_fuel_type(raw) == slug


# ---------------------------------------------------------------------------
# Transformer tests (pure, no mocks)
# ---------------------------------------------------------------------------


class TestTransformDayAheadPrices:
    def test_basic(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
        series = pd.Series([50.0, 55.0, 60.0], index=idx)
        rows = transform_day_ahead_prices(series, BiddingZone.EE)
        assert len(rows) == 3
        assert rows[0].price_eur_mwh == 50.0
        assert rows[0].zone == BiddingZone.EE
        assert rows[0].period_start == datetime(2024, 1, 1, 0, tzinfo=UTC)
        assert rows[0].period_end == datetime(2024, 1, 1, 1, tzinfo=UTC)

    def test_nan_skipped(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
        series = pd.Series([50.0, np.nan, 60.0], index=idx)
        rows = transform_day_ahead_prices(series, BiddingZone.FI)
        assert len(rows) == 2

    def test_non_utc_converted(self):
        idx = pd.date_range("2024-01-01", periods=2, freq="h", tz="Europe/Tallinn")
        series = pd.Series([40.0, 45.0], index=idx)
        rows = transform_day_ahead_prices(series, BiddingZone.EE)
        assert len(rows) == 2
        # Tallinn is UTC+2 in winter
        assert rows[0].period_start == datetime(2023, 12, 31, 22, tzinfo=UTC)


class TestTransformGeneration:
    def test_multiindex_columns(self):
        """entsoe-py returns MultiIndex (fuel_type, aggregation) columns."""
        idx = pd.date_range("2024-06-01", periods=2, freq="h", tz="UTC")
        columns = pd.MultiIndex.from_tuples(
            [
                ("Wind Onshore", "Actual Aggregated"),
                ("Wind Onshore", "Actual Consumption"),
                ("Fossil Gas", "Actual Aggregated"),
            ]
        )
        data = [[100.0, 10.0, 200.0], [110.0, 11.0, 210.0]]
        df = pd.DataFrame(data, index=idx, columns=columns)

        rows = transform_generation(df, BiddingZone.LT)
        # Should only include "Actual Aggregated" entries: 2 fuel types x 2 hours = 4
        assert len(rows) == 4
        fuel_types = {r.fuel_type for r in rows}
        assert fuel_types == {"wind_onshore", "gas"}

    def test_flat_columns(self):
        """Handle flat string columns (some entsoe-py versions)."""
        idx = pd.date_range("2024-06-01", periods=1, freq="h", tz="UTC")
        df = pd.DataFrame({"Solar": [300.0], "Nuclear": [500.0]}, index=idx)

        rows = transform_generation(df, BiddingZone.FI)
        assert len(rows) == 2
        assert {r.fuel_type for r in rows} == {"solar", "nuclear"}

    def test_nan_skipped(self):
        idx = pd.date_range("2024-06-01", periods=1, freq="h", tz="UTC")
        df = pd.DataFrame({"Solar": [np.nan], "Nuclear": [500.0]}, index=idx)
        rows = transform_generation(df, BiddingZone.FI)
        assert len(rows) == 1


class TestTransformLoad:
    def test_basic(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
        df = pd.DataFrame({"Actual Load": [1000.0, 1100.0, 1200.0]}, index=idx)
        rows = transform_load(df, BiddingZone.LV, is_forecast=False)
        assert len(rows) == 3
        assert rows[0].load_mw == 1000.0
        assert rows[0].is_forecast is False

    def test_forecast(self):
        idx = pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC")
        df = pd.DataFrame({"Forecasted Load": [900.0, 950.0]}, index=idx)
        rows = transform_load(df, BiddingZone.EE, is_forecast=True)
        assert len(rows) == 2
        assert all(r.is_forecast is True for r in rows)


class TestTransformCrossBorderFlows:
    def test_basic(self):
        idx = pd.date_range("2024-03-01", periods=3, freq="h", tz="UTC")
        series = pd.Series([400.0, -50.0, 300.0], index=idx)
        rows = transform_cross_border_flows(series, "EE", "FI")
        assert len(rows) == 3
        assert rows[0].from_zone == "EE"
        assert rows[0].to_zone == "FI"
        assert rows[1].flow_mw == -50.0

    def test_nan_skipped(self):
        idx = pd.date_range("2024-03-01", periods=2, freq="h", tz="UTC")
        series = pd.Series([np.nan, 100.0], index=idx)
        rows = transform_cross_border_flows(series, "LV", "LT")
        assert len(rows) == 1


class TestTransformOutages:
    def _make_outage_df(self):
        """Create a sample outage DataFrame mimicking entsoe-py output."""
        return pd.DataFrame(
            {
                "mrid": ["UM-001", "UM-001", "UM-002"],
                "revision": [1, 2, 1],
                "businesstype": [
                    "Unplanned outage of a generation unit",
                    "Unplanned outage of a generation unit",
                    "Planned maintenance",
                ],
                "production_resource_name": ["Plant A", "Plant A", "Plant B"],
                "production_type": ["Fossil Gas", "Fossil Gas", "Nuclear"],
                "nominal_power": [500.0, 500.0, 1000.0],
                "available_capacity": [0.0, 100.0, 200.0],
                "start": [
                    pd.Timestamp("2024-05-01", tz="UTC"),
                    pd.Timestamp("2024-05-01", tz="UTC"),
                    pd.Timestamp("2024-06-01", tz="UTC"),
                ],
                "end": [
                    pd.Timestamp("2024-05-10", tz="UTC"),
                    pd.Timestamp("2024-05-12", tz="UTC"),
                    pd.NaT,
                ],
                "status": ["Active", "Active", "Active"],
            }
        )

    def test_dedup_by_latest_revision(self):
        df = self._make_outage_df()
        rows = transform_outages(df, BiddingZone.FI)
        mrids = [r.message_id for r in rows]
        assert mrids.count("UM-001") == 1
        # Latest revision (rev 2): unavailable = 500 - 100 = 400
        um001 = next(r for r in rows if r.message_id == "UM-001")
        assert um001.unavailable_mw == 400.0

    def test_cancelled_filtered(self):
        df = self._make_outage_df()
        df.loc[2, "status"] = "Cancelled"
        rows = transform_outages(df, BiddingZone.FI)
        assert all(r.message_id != "UM-002" for r in rows)

    def test_business_type_mapping(self):
        df = self._make_outage_df()
        rows = transform_outages(df, BiddingZone.FI)
        um001 = next(r for r in rows if r.message_id == "UM-001")
        um002 = next(r for r in rows if r.message_id == "UM-002")
        assert um001.outage_type == "unplanned"
        assert um002.outage_type == "planned"

    def test_end_time_nat(self):
        df = self._make_outage_df()
        rows = transform_outages(df, BiddingZone.FI)
        um002 = next(r for r in rows if r.message_id == "UM-002")
        assert um002.period_end is None

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        rows = transform_outages(df, BiddingZone.EE)
        assert rows == []

    def test_nan_capacity_yields_zero(self):
        """NaN nominal_power / available_capacity must not produce NaN unavailable_mw."""
        df = self._make_outage_df()
        df.loc[0, "nominal_power"] = np.nan
        df.loc[0, "available_capacity"] = np.nan
        rows = transform_outages(df, BiddingZone.FI)
        for r in rows:
            assert r.unavailable_mw == r.unavailable_mw  # NaN != NaN
            assert not pd.isna(r.unavailable_mw)


# ---------------------------------------------------------------------------
# Client / mapping tests
# ---------------------------------------------------------------------------


class TestZoneMapping:
    def test_all_zones_mapped(self):
        for zone in BiddingZone:
            assert zone in ZONE_TO_ENTSOE

    def test_swedish_zones(self):
        assert ZONE_TO_ENTSOE[BiddingZone.SE4] == "SE_4"
        assert ZONE_TO_ENTSOE[BiddingZone.SE3] == "SE_3"

    def test_borders_use_valid_entsoe_codes(self):
        from entsoe.mappings import NEIGHBOURS

        all_codes = set(NEIGHBOURS.keys()) | {
            n for neighbours in NEIGHBOURS.values() for n in neighbours
        }
        for a, b in BORDERS:
            assert a in all_codes, f"{a} not a known ENTSO-E code"
            assert b in all_codes, f"{b} not a known ENTSO-E code"

    def test_all_neighbours_accounted_for(self):
        """Every NEIGHBOURS link touching our zones is in BORDERS, except RU/BY."""
        from entsoe.mappings import NEIGHBOURS

        from grid_signals.ingestion.client import (
            _EXTERNAL_LINKS,  # noqa: PLC2701
            _INTERNAL_LINKS,  # noqa: PLC2701
        )

        # RU, RU_KGD, BY desyncronised around feb 2025, DE_AT_LU renamed to DE_LU around oct 2018
        excluded = {"RU", "RU_KGD", "BY", "DE_AT_LU"}
        our_zones = set(ZONE_TO_ENTSOE.values())

        expected = set()
        for zone, neighbours in NEIGHBOURS.items():
            if zone not in our_zones:
                continue
            for n in neighbours:
                if n in excluded:
                    continue
                expected.add(tuple(sorted([zone, n])))

        actual = {tuple(sorted(pair)) for pair in _INTERNAL_LINKS + _EXTERNAL_LINKS}

        missing = expected - actual
        assert not missing, f"Missing border links: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Integration tests (mocked client + in-memory DuckDB)
# ---------------------------------------------------------------------------


class TestIngestDayAheadPrices:
    def test_happy_path(self, con):
        client = MagicMock()
        idx = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")
        client.query_day_ahead_prices.return_value = pd.Series(
            range(24), index=idx, dtype=float
        )
        count = ingest_day_ahead_prices(
            con,
            client,
            [BiddingZone.EE],
            pd.Timestamp("2024-01-01", tz="UTC"),
            pd.Timestamp("2024-01-02", tz="UTC"),
        )
        assert count == 24
        rows = get_day_ahead_prices(
            con,
            BiddingZone.EE,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert len(rows) == 24

    def test_no_matching_data(self, con):
        client = MagicMock()
        client.query_day_ahead_prices.side_effect = NoMatchingDataError
        count = ingest_day_ahead_prices(
            con,
            client,
            [BiddingZone.EE],
            pd.Timestamp("2024-01-01", tz="UTC"),
            pd.Timestamp("2024-01-02", tz="UTC"),
        )
        assert count == 0

    def test_generic_exception(self, con):
        client = MagicMock()
        client.query_day_ahead_prices.side_effect = RuntimeError("API down")
        count = ingest_day_ahead_prices(
            con,
            client,
            [BiddingZone.EE],
            pd.Timestamp("2024-01-01", tz="UTC"),
            pd.Timestamp("2024-01-02", tz="UTC"),
        )
        assert count == 0


class TestIngestGeneration:
    def test_happy_path(self, con):
        client = MagicMock()
        idx = pd.date_range("2024-06-01", periods=2, freq="h", tz="UTC")
        columns = pd.MultiIndex.from_tuples(
            [
                ("Wind Onshore", "Actual Aggregated"),
                ("Fossil Gas", "Actual Aggregated"),
            ]
        )
        df = pd.DataFrame([[100.0, 200.0], [110.0, 210.0]], index=idx, columns=columns)
        client.query_generation.return_value = df
        count = ingest_generation_per_type(
            con,
            client,
            [BiddingZone.LT],
            pd.Timestamp("2024-06-01", tz="UTC"),
            pd.Timestamp("2024-06-02", tz="UTC"),
        )
        assert count == 4


class TestIngestTotalLoad:
    def test_happy_path(self, con):
        client = MagicMock()
        idx = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
        client.query_load.return_value = pd.DataFrame(
            {"Actual Load": [1000.0, 1100.0, 1200.0]}, index=idx
        )
        client.query_load_forecast.return_value = pd.DataFrame(
            {"Forecasted Load": [950.0, 1050.0, 1150.0]}, index=idx
        )
        count = ingest_total_load(
            con,
            client,
            [BiddingZone.LV],
            pd.Timestamp("2024-01-01", tz="UTC"),
            pd.Timestamp("2024-01-02", tz="UTC"),
        )
        assert count == 6  # 3 actual + 3 forecast


class TestIngestCrossBorderFlows:
    def test_happy_path(self, con):
        client = MagicMock()
        idx = pd.date_range("2024-03-01", periods=2, freq="h", tz="UTC")
        client.query_crossborder_flows.return_value = pd.Series(
            [400.0, 350.0], index=idx
        )
        count = ingest_cross_border_flows(
            con,
            client,
            [("EE", "FI")],
            pd.Timestamp("2024-03-01", tz="UTC"),
            pd.Timestamp("2024-03-02", tz="UTC"),
        )
        assert count == 2


class TestIngestOutages:
    def test_happy_path(self, con):
        client = MagicMock()
        client.query_unavailability_of_generation_units.return_value = pd.DataFrame(
            {
                "mrid": ["UM-100"],
                "revision": [1],
                "businesstype": ["Planned maintenance"],
                "production_resource_name": ["Test Plant"],
                "production_type": ["Nuclear"],
                "nominal_power": [1000.0],
                "available_capacity": [0.0],
                "start": [pd.Timestamp("2024-05-01", tz="UTC")],
                "end": [pd.Timestamp("2024-05-15", tz="UTC")],
                "status": ["Active"],
            }
        )
        count = ingest_outages(
            con,
            client,
            [BiddingZone.FI],
            pd.Timestamp("2024-05-01", tz="UTC"),
            pd.Timestamp("2024-06-01", tz="UTC"),
        )
        assert count == 1
        outages = get_outages(con, BiddingZone.FI)
        assert len(outages) == 1
        assert outages[0].unavailable_mw == 1000.0

    def test_no_matching_data(self, con):
        client = MagicMock()
        client.query_unavailability_of_generation_units.side_effect = (
            NoMatchingDataError
        )
        count = ingest_outages(
            con,
            client,
            [BiddingZone.FI],
            pd.Timestamp("2024-05-01", tz="UTC"),
            pd.Timestamp("2024-06-01", tz="UTC"),
        )
        assert count == 0


class TestRetryOnServerError:
    def _make_http_error(self, status_code: int):
        response = MagicMock()
        response.status_code = status_code
        return requests.exceptions.HTTPError(response=response)

    @patch("grid_signals.ingestion.entsoe.sleep")
    def test_retries_on_503_then_succeeds(self, mock_sleep):
        fn = MagicMock(side_effect=[self._make_http_error(503), "ok"])
        result = _retry_on_server_error(fn, "arg1", key="val")
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(5)

    @patch("grid_signals.ingestion.entsoe.sleep")
    def test_raises_after_max_retries(self, mock_sleep):  # noqa: ARG002
        fn = MagicMock(side_effect=[self._make_http_error(502)] * 3)
        with pytest.raises(requests.exceptions.HTTPError):
            _retry_on_server_error(fn)
        assert fn.call_count == 3

    def test_does_not_retry_on_4xx(self):
        fn = MagicMock(side_effect=self._make_http_error(404))
        with pytest.raises(requests.exceptions.HTTPError):
            _retry_on_server_error(fn)
        assert fn.call_count == 1
