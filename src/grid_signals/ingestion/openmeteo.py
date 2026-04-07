"""Orchestrator functions: fetch from Open-Meteo, transform, insert into PostgreSQL."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    import psycopg

    from grid_signals.ingestion.locations import WeatherLocation

from grid_signals.db.queries import insert_weather_forecasts
from grid_signals.ingestion.weather_client import fetch_forecast, fetch_history
from grid_signals.ingestion.weather_transformers import transform_weather_response

logger = logging.getLogger(__name__)


def ingest_weather_forecasts(
    con: psycopg.Connection,
    client: httpx.Client,
    locations: list[WeatherLocation],
    start: datetime,
    end: datetime,
) -> int:
    """Fetch and store weather forecasts for the given locations."""
    total = 0
    fetched_at = datetime.now(UTC)
    for loc in locations:
        try:
            data = fetch_forecast(client, loc, start.date(), end.date())
            rows = transform_weather_response(data, loc, fetched_at)
            total += insert_weather_forecasts(con, rows)
            logger.info("weather_forecast: %s → %d rows", loc.name, len(rows))
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "weather_forecast: HTTP %d for %s", exc.response.status_code, loc.name
            )
        except Exception:
            logger.exception("weather_forecast: error for %s", loc.name)
    return total


def ingest_weather_history(
    con: psycopg.Connection,
    client: httpx.Client,
    locations: list[WeatherLocation],
    start: datetime,
    end: datetime,
) -> int:
    """Fetch and store historical weather for the given locations."""
    total = 0
    fetched_at = datetime.now(UTC)
    for loc in locations:
        try:
            data = fetch_history(client, loc, start.date(), end.date())
            rows = transform_weather_response(data, loc, fetched_at)
            total += insert_weather_forecasts(con, rows)
            logger.info("weather_history: %s → %d rows", loc.name, len(rows))
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "weather_history: HTTP %d for %s", exc.response.status_code, loc.name
            )
        except Exception:
            logger.exception("weather_history: error for %s", loc.name)
    return total
