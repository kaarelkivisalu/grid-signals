"""Open-Meteo API client: forecast and historical weather data."""

from datetime import date

import httpx

from grid_signals.ingestion.locations import WeatherLocation

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_HOURLY_VARS = "wind_speed_100m,shortwave_radiation,temperature_2m"
_COMMON_PARAMS = {
    "hourly": _HOURLY_VARS,
    "wind_speed_unit": "ms",
    "timezone": "UTC",
}


def get_openmeteo_client() -> httpx.Client:
    """Create an httpx Client with reasonable defaults for Open-Meteo."""
    return httpx.Client(timeout=30.0)


def fetch_forecast(
    client: httpx.Client,
    location: WeatherLocation,
    start_date: date,
    end_date: date,
) -> dict:
    """Fetch hourly weather forecast from Open-Meteo.

    Returns the raw JSON response dict.
    """
    params = {
        **_COMMON_PARAMS,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    resp = client.get(FORECAST_URL, params=params)
    resp.raise_for_status()
    return resp.json()


def fetch_history(
    client: httpx.Client,
    location: WeatherLocation,
    start_date: date,
    end_date: date,
) -> dict:
    """Fetch historical hourly weather from Open-Meteo Archive API.

    Returns the raw JSON response dict.
    """
    params = {
        **_COMMON_PARAMS,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    resp = client.get(ARCHIVE_URL, params=params)
    resp.raise_for_status()
    return resp.json()
