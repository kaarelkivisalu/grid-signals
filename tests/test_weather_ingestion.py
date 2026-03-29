"""Tests for the Open-Meteo weather ingestion layer.

- Transformer tests: pure functions, no mocks
- Client tests: verify URL/params construction
- Integration tests: mocked HTTP + in-memory DuckDB
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import duckdb
import httpx
import pytest

from grid_signals.db.queries import get_weather_forecasts, insert_weather_forecasts
from grid_signals.db.schema import create_tables
from grid_signals.ingestion.locations import LOCATIONS, WeatherLocation
from grid_signals.ingestion.openmeteo import (
    ingest_weather_forecasts,
    ingest_weather_history,
)
from grid_signals.ingestion.weather_client import (
    ARCHIVE_URL,
    FORECAST_URL,
    fetch_forecast,
    fetch_history,
)
from grid_signals.ingestion.weather_transformers import transform_weather_response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_LOCATION = WeatherLocation("TEST_loc", 56.0, 14.0)


@pytest.fixture
def con():
    """In-memory DuckDB with all tables created."""
    c = duckdb.connect(":memory:")
    create_tables(c)
    yield c
    c.close()


def _make_openmeteo_response(hours: int = 24) -> dict:
    """Build a minimal Open-Meteo JSON response."""
    times = [
        f"2024-07-01T{h:02d}:00" for h in range(hours)
    ]
    return {
        "hourly": {
            "time": times,
            "wind_speed_100m": [8.5 + i * 0.1 for i in range(hours)],
            "shortwave_radiation": [max(0, 400 - abs(12 - i) * 50) for i in range(hours)],
            "temperature_2m": [18.0 + i * 0.2 for i in range(hours)],
        }
    }


# ---------------------------------------------------------------------------
# Location tests
# ---------------------------------------------------------------------------


class TestLocations:
    def test_all_locations_have_valid_coords(self):
        for loc in LOCATIONS:
            assert -90 <= loc.latitude <= 90
            assert -180 <= loc.longitude <= 180
            assert loc.name

    def test_expected_count(self):
        assert len(LOCATIONS) == 16


# ---------------------------------------------------------------------------
# Transformer tests (pure, no mocks)
# ---------------------------------------------------------------------------


class TestTransformWeatherResponse:
    def test_basic(self):
        data = _make_openmeteo_response(3)
        fetched_at = datetime(2024, 7, 1, 6, tzinfo=UTC)
        rows = transform_weather_response(data, SAMPLE_LOCATION, fetched_at)

        assert len(rows) == 3
        assert rows[0].location_name == "TEST_loc"
        assert rows[0].latitude == 56.0
        assert rows[0].longitude == 14.0
        assert rows[0].period_start == datetime(2024, 7, 1, 0, tzinfo=UTC)
        assert rows[0].period_end == datetime(2024, 7, 1, 1, tzinfo=UTC)
        assert rows[0].fetched_at == fetched_at
        assert rows[0].wind_speed_100m_ms == 8.5
        assert rows[0].temperature_c == 18.0

    def test_all_none_skipped(self):
        data = {
            "hourly": {
                "time": ["2024-07-01T00:00", "2024-07-01T01:00"],
                "wind_speed_100m": [None, 5.0],
                "shortwave_radiation": [None, 100.0],
                "temperature_2m": [None, 15.0],
            }
        }
        rows = transform_weather_response(
            data, SAMPLE_LOCATION, datetime(2024, 7, 1, tzinfo=UTC)
        )
        assert len(rows) == 1
        assert rows[0].wind_speed_100m_ms == 5.0

    def test_partial_none_kept(self):
        """Hours with some (but not all) None values are kept."""
        data = {
            "hourly": {
                "time": ["2024-07-01T00:00"],
                "wind_speed_100m": [7.0],
                "shortwave_radiation": [None],
                "temperature_2m": [20.0],
            }
        }
        rows = transform_weather_response(
            data, SAMPLE_LOCATION, datetime(2024, 7, 1, tzinfo=UTC)
        )
        assert len(rows) == 1
        assert rows[0].solar_irradiance_wm2 is None
        assert rows[0].wind_speed_100m_ms == 7.0

    def test_timestamps_are_utc(self):
        data = _make_openmeteo_response(1)
        rows = transform_weather_response(
            data, SAMPLE_LOCATION, datetime(2024, 7, 1, tzinfo=UTC)
        )
        assert rows[0].period_start.tzinfo == UTC


# ---------------------------------------------------------------------------
# Client tests (mocked httpx)
# ---------------------------------------------------------------------------


class TestFetchForecast:
    def test_calls_correct_url(self):
        mock_response = MagicMock()
        mock_response.json.return_value = _make_openmeteo_response(1)
        mock_response.raise_for_status = MagicMock()

        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_response

        from datetime import date

        result = fetch_forecast(
            client, SAMPLE_LOCATION, date(2024, 7, 1), date(2024, 7, 7)
        )

        client.get.assert_called_once()
        call_args = client.get.call_args
        assert call_args[0][0] == FORECAST_URL
        params = call_args[1]["params"]
        assert params["latitude"] == 56.0
        assert params["longitude"] == 14.0
        assert params["start_date"] == "2024-07-01"
        assert params["end_date"] == "2024-07-07"
        assert params["wind_speed_unit"] == "ms"
        assert "wind_speed_100m" in params["hourly"]
        assert result == _make_openmeteo_response(1)

    def test_raises_on_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=MagicMock(status_code=400)
        )
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_response

        from datetime import date

        with pytest.raises(httpx.HTTPStatusError):
            fetch_forecast(client, SAMPLE_LOCATION, date(2024, 7, 1), date(2024, 7, 7))


class TestFetchHistory:
    def test_calls_archive_url(self):
        mock_response = MagicMock()
        mock_response.json.return_value = _make_openmeteo_response(1)
        mock_response.raise_for_status = MagicMock()

        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_response

        from datetime import date

        fetch_history(client, SAMPLE_LOCATION, date(2024, 1, 1), date(2024, 1, 31))

        call_args = client.get.call_args
        assert call_args[0][0] == ARCHIVE_URL


# ---------------------------------------------------------------------------
# Integration tests (mocked fetch + in-memory DuckDB)
# ---------------------------------------------------------------------------


class TestIngestWeatherForecasts:
    @patch("grid_signals.ingestion.openmeteo.fetch_forecast")
    def test_happy_path(self, mock_fetch, con):
        mock_fetch.return_value = _make_openmeteo_response(24)

        count = ingest_weather_forecasts(
            con,
            MagicMock(spec=httpx.Client),
            [SAMPLE_LOCATION],
            datetime(2024, 7, 1, tzinfo=UTC),
            datetime(2024, 7, 2, tzinfo=UTC),
        )
        assert count == 24

        rows = get_weather_forecasts(
            con,
            "TEST_loc",
            datetime(2024, 7, 1, tzinfo=UTC),
            datetime(2024, 7, 2, tzinfo=UTC),
        )
        assert len(rows) == 24

    @patch("grid_signals.ingestion.openmeteo.fetch_forecast")
    def test_http_error_continues(self, mock_fetch, con):
        mock_fetch.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        count = ingest_weather_forecasts(
            con,
            MagicMock(spec=httpx.Client),
            [SAMPLE_LOCATION],
            datetime(2024, 7, 1, tzinfo=UTC),
            datetime(2024, 7, 2, tzinfo=UTC),
        )
        assert count == 0

    @patch("grid_signals.ingestion.openmeteo.fetch_forecast")
    def test_generic_exception_continues(self, mock_fetch, con):
        mock_fetch.side_effect = RuntimeError("network down")
        count = ingest_weather_forecasts(
            con,
            MagicMock(spec=httpx.Client),
            [SAMPLE_LOCATION],
            datetime(2024, 7, 1, tzinfo=UTC),
            datetime(2024, 7, 2, tzinfo=UTC),
        )
        assert count == 0

    @patch("grid_signals.ingestion.openmeteo.fetch_forecast")
    def test_multiple_locations(self, mock_fetch, con):
        mock_fetch.return_value = _make_openmeteo_response(3)
        loc2 = WeatherLocation("TEST_loc2", 59.0, 25.0)

        count = ingest_weather_forecasts(
            con,
            MagicMock(spec=httpx.Client),
            [SAMPLE_LOCATION, loc2],
            datetime(2024, 7, 1, tzinfo=UTC),
            datetime(2024, 7, 2, tzinfo=UTC),
        )
        assert count == 6  # 3 per location


class TestIngestWeatherHistory:
    @patch("grid_signals.ingestion.openmeteo.fetch_history")
    def test_happy_path(self, mock_fetch, con):
        mock_fetch.return_value = _make_openmeteo_response(24)

        count = ingest_weather_history(
            con,
            MagicMock(spec=httpx.Client),
            [SAMPLE_LOCATION],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert count == 24

    @patch("grid_signals.ingestion.openmeteo.fetch_history")
    def test_http_error_continues(self, mock_fetch, con):
        mock_fetch.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )
        count = ingest_weather_history(
            con,
            MagicMock(spec=httpx.Client),
            [SAMPLE_LOCATION],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert count == 0
