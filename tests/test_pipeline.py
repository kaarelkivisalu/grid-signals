"""Tests for the pipeline orchestration and validation modules.

- Validation tests: pure in-memory DuckDB, no mocks
- Pipeline integration tests: mocked external clients
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import duckdb
import httpx
import pandas as pd
import pytest

from grid_signals.db.schema import create_tables
from grid_signals.models import BiddingZone, DayAheadPrice, WeatherForecast
from grid_signals.db.queries import insert_day_ahead_prices, insert_weather_forecasts
from grid_signals.validation import (
    validate_price_bounds,
    validate_price_completeness,
    validate_weather_freshness,
)

_1H = timedelta(hours=1)
_15M = timedelta(minutes=15)


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
# Validation: price completeness
# ---------------------------------------------------------------------------


class TestPriceCompleteness:
    def test_pass_24_hours(self, con):
        rows = [
            DayAheadPrice(
                zone=BiddingZone.EE,
                period_start=datetime(2024, 1, 15, h, tzinfo=UTC),
                period_end=datetime(2024, 1, 15, h, tzinfo=UTC) + _1H,
                price_eur_mwh=50.0,
            )
            for h in range(24)
        ]
        insert_day_ahead_prices(con, rows)

        results = validate_price_completeness(
            con, BiddingZone.EE, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert len(results) == 1
        assert results[0].passed is True

    def test_fail_missing_hours(self, con):
        rows = [
            DayAheadPrice(
                zone=BiddingZone.EE,
                period_start=datetime(2024, 1, 15, h, tzinfo=UTC),
                period_end=datetime(2024, 1, 15, h, tzinfo=UTC) + _1H,
                price_eur_mwh=50.0,
            )
            for h in range(10)
        ]
        insert_day_ahead_prices(con, rows)

        results = validate_price_completeness(
            con, BiddingZone.EE, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "10 intervals" in results[0].detail

    def test_pass_23_hours_dst(self, con):
        """23 hours is valid (DST spring-forward)."""
        rows = [
            DayAheadPrice(
                zone=BiddingZone.EE,
                period_start=datetime(2024, 3, 31, h, tzinfo=UTC),
                period_end=datetime(2024, 3, 31, h, tzinfo=UTC) + _1H,
                price_eur_mwh=50.0,
            )
            for h in range(23)
        ]
        insert_day_ahead_prices(con, rows)

        results = validate_price_completeness(
            con, BiddingZone.EE, datetime(2024, 3, 31, tzinfo=UTC)
        )
        assert results[0].passed is True

    def test_pass_96_quarters(self, con):
        """96 quarter-hourly intervals is a complete day at 15-min resolution."""
        rows = [
            DayAheadPrice(
                zone=BiddingZone.EE,
                period_start=datetime(2024, 1, 15, h, m, tzinfo=UTC),
                period_end=datetime(2024, 1, 15, h, m, tzinfo=UTC) + _15M,
                price_eur_mwh=50.0,
            )
            for h in range(24)
            for m in (0, 15, 30, 45)
        ]
        insert_day_ahead_prices(con, rows)

        results = validate_price_completeness(
            con, BiddingZone.EE, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert len(results) == 1
        assert results[0].passed is True
        assert "15min" in results[0].detail

    def test_fail_empty_day(self, con):
        results = validate_price_completeness(
            con, BiddingZone.EE, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert results[0].passed is False
        assert "0 intervals" in results[0].detail


# ---------------------------------------------------------------------------
# Validation: price bounds
# ---------------------------------------------------------------------------


class TestPriceBounds:
    def test_pass_normal_prices(self, con):
        rows = [
            DayAheadPrice(
                zone=BiddingZone.FI,
                period_start=datetime(2024, 1, 15, h, tzinfo=UTC),
                period_end=datetime(2024, 1, 15, h, tzinfo=UTC) + _1H,
                price_eur_mwh=50.0 + h,
            )
            for h in range(24)
        ]
        insert_day_ahead_prices(con, rows)

        results = validate_price_bounds(
            con, BiddingZone.FI, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert len(results) == 1
        assert results[0].passed is True

    def test_fail_extreme_high(self, con):
        ts = datetime(2024, 1, 15, 0, tzinfo=UTC)
        rows = [
            DayAheadPrice(
                zone=BiddingZone.FI,
                period_start=ts,
                period_end=ts + _1H,
                price_eur_mwh=5000.0,
            ),
        ]
        insert_day_ahead_prices(con, rows)

        results = validate_price_bounds(
            con, BiddingZone.FI, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert results[0].passed is False
        assert "1 prices outside" in results[0].detail

    def test_fail_extreme_low(self, con):
        ts = datetime(2024, 1, 15, 0, tzinfo=UTC)
        rows = [
            DayAheadPrice(
                zone=BiddingZone.FI,
                period_start=ts,
                period_end=ts + _1H,
                price_eur_mwh=-600.0,
            ),
        ]
        insert_day_ahead_prices(con, rows)

        results = validate_price_bounds(
            con, BiddingZone.FI, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert results[0].passed is False

    def test_pass_empty_day(self, con):
        """No data means no outliers — passes."""
        results = validate_price_bounds(
            con, BiddingZone.FI, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert results[0].passed is True


# ---------------------------------------------------------------------------
# Validation: weather freshness
# ---------------------------------------------------------------------------


class TestWeatherFreshness:
    def test_pass_recent(self, con):
        now = datetime.now(UTC)
        rows = [
            WeatherForecast(
                location_name="EE",
                latitude=59.0,
                longitude=25.0,
                period_start=now,
                period_end=now + timedelta(hours=1),
                fetched_at=now - timedelta(hours=1),
                wind_speed_100m_ms=8.0,
                solar_irradiance_wm2=100.0,
                temperature_c=15.0,
            )
        ]
        insert_weather_forecasts(con, rows)

        results = validate_weather_freshness(con, "EE")
        assert len(results) == 1
        assert results[0].passed is True

    def test_fail_stale(self, con):
        old = datetime.now(UTC) - timedelta(hours=24)
        rows = [
            WeatherForecast(
                location_name="EE",
                latitude=59.0,
                longitude=25.0,
                period_start=old,
                period_end=old + timedelta(hours=1),
                fetched_at=old,
                wind_speed_100m_ms=8.0,
                solar_irradiance_wm2=100.0,
                temperature_c=15.0,
            )
        ]
        insert_weather_forecasts(con, rows)

        results = validate_weather_freshness(con, "EE")
        assert results[0].passed is False

    def test_fail_no_data(self, con):
        results = validate_weather_freshness(con, "NONEXISTENT")
        assert results[0].passed is False
        assert "no weather data" in results[0].detail


# ---------------------------------------------------------------------------
# Pipeline integration: run_daily (mocked ENTSO-E)
# ---------------------------------------------------------------------------


class TestRunDaily:
    @patch("grid_signals.pipeline.get_entsoe_client")
    @patch("grid_signals.pipeline.get_connection")
    def test_run_daily(self, mock_get_con, mock_get_client):
        # Set up in-memory DB
        con = duckdb.connect(":memory:")
        create_tables(con)
        mock_get_con.return_value = con

        # Mock ENTSO-E client: return valid data for prices, empty for rest
        client = MagicMock()
        mock_get_client.return_value = client

        idx = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")
        client.query_day_ahead_prices.return_value = pd.Series(
            range(24), index=idx, dtype=float
        )

        # Generation: MultiIndex columns
        columns = pd.MultiIndex.from_tuples([
            ("Wind Onshore", "Actual Aggregated"),
        ])
        gen_df = pd.DataFrame([[100.0]] * 24, index=idx, columns=columns)
        client.query_generation.return_value = gen_df

        # Load
        client.query_load.return_value = pd.DataFrame(
            {"Actual Load": [1000.0] * 24}, index=idx
        )
        client.query_load_forecast.return_value = pd.DataFrame(
            {"Forecasted Load": [950.0] * 24}, index=idx
        )

        # Cross-border flows
        client.query_crossborder_flows.return_value = pd.Series(
            [100.0] * 24, index=idx
        )

        # Outages
        client.query_unavailability_of_generation_units.return_value = pd.DataFrame({
            "mrid": ["UM-1"],
            "revision": [1],
            "businesstype": ["Planned maintenance"],
            "production_resource_name": ["Test"],
            "production_type": ["Nuclear"],
            "nominal_power": [500.0],
            "available_capacity": [0.0],
            "start": [pd.Timestamp("2024-01-01", tz="UTC")],
            "end": [pd.Timestamp("2024-01-10", tz="UTC")],
            "status": ["Active"],
        })

        from grid_signals.pipeline import run_daily

        total = run_daily()
        assert total > 0


# ---------------------------------------------------------------------------
# Pipeline integration: run_weather (mocked Open-Meteo)
# ---------------------------------------------------------------------------


class TestRunWeather:
    @patch("grid_signals.pipeline.get_openmeteo_client")
    @patch("grid_signals.pipeline.get_connection")
    @patch("grid_signals.ingestion.openmeteo.fetch_forecast")
    def test_run_weather(self, mock_fetch, mock_get_con, mock_get_client):
        con = duckdb.connect(":memory:")
        create_tables(con)
        mock_get_con.return_value = con
        mock_get_client.return_value = MagicMock(spec=httpx.Client)

        hours = 24
        mock_fetch.return_value = {
            "hourly": {
                "time": [f"2024-07-01T{h:02d}:00" for h in range(hours)],
                "wind_speed_100m": [8.0] * hours,
                "shortwave_radiation": [200.0] * hours,
                "temperature_2m": [18.0] * hours,
            }
        }

        from grid_signals.pipeline import run_weather

        total = run_weather()
        assert total > 0
