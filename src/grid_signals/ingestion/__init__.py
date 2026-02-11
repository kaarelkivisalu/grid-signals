"""Data ingestion layer (ENTSO-E + Open-Meteo)."""

from grid_signals.ingestion.client import get_entsoe_client
from grid_signals.ingestion.entsoe import (
    ingest_cross_border_flows,
    ingest_day_ahead_prices,
    ingest_generation_per_type,
    ingest_outages,
    ingest_total_load,
)
from grid_signals.ingestion.locations import LOCATIONS, WeatherLocation
from grid_signals.ingestion.openmeteo import (
    ingest_weather_forecasts,
    ingest_weather_history,
)
from grid_signals.ingestion.weather_client import get_openmeteo_client

__all__ = [
    # ENTSO-E
    "get_entsoe_client",
    "ingest_cross_border_flows",
    "ingest_day_ahead_prices",
    "ingest_generation_per_type",
    "ingest_outages",
    "ingest_total_load",
    # Open-Meteo
    "get_openmeteo_client",
    "ingest_weather_forecasts",
    "ingest_weather_history",
    "LOCATIONS",
    "WeatherLocation",
]
