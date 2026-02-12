"""Targeted backfill script: fill gaps in load, flows, outages, and weather.

Usage:
    uv run python scripts/backfill_gaps.py
"""

import logging
import sys
from datetime import UTC, datetime, timedelta

import pandas as pd

from grid_signals.db.connection import DEFAULT_DB_PATH, get_connection
from grid_signals.db.schema import create_tables
from grid_signals.ingestion.client import BORDERS, get_entsoe_client
from grid_signals.ingestion.entsoe import (
    ingest_cross_border_flows,
    ingest_day_ahead_prices,
    ingest_generation_per_type,
    ingest_outages,
    ingest_total_load,
)
from grid_signals.ingestion.locations import LOCATIONS
from grid_signals.ingestion.openmeteo import ingest_weather_history
from grid_signals.ingestion.weather_client import get_openmeteo_client
from grid_signals.models.zones import BiddingZone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Backfill target: 6 months back from today
END = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
START = datetime(2025, 8, 1, tzinfo=UTC)
CHUNK_DAYS = 30  # ENTSO-E works well with ~1 month chunks

zones = list(BiddingZone)


def backfill_entsoe_chunked(con, client, start, end):
    """Backfill ENTSO-E data in monthly chunks to respect rate limits."""
    current = start
    total = 0
    while current < end:
        chunk_end = min(current + timedelta(days=CHUNK_DAYS), end)
        s = pd.Timestamp(current)
        e = pd.Timestamp(chunk_end)
        label = f"{current.date()} → {chunk_end.date()}"

        logger.info("=== Chunk: %s ===", label)

        n = ingest_day_ahead_prices(con, client, zones, s, e)
        logger.info("  prices: %d rows", n)
        total += n

        n = ingest_generation_per_type(con, client, zones, s, e)
        logger.info("  generation: %d rows", n)
        total += n

        n = ingest_total_load(con, client, zones, s, e)
        logger.info("  load: %d rows", n)
        total += n

        n = ingest_cross_border_flows(con, client, BORDERS, s, e)
        logger.info("  flows: %d rows", n)
        total += n

        n = ingest_outages(con, client, zones, s, e)
        logger.info("  outages: %d rows", n)
        total += n

        current = chunk_end

    return total


def backfill_weather(con, start, end):
    """Backfill weather history from Open-Meteo."""
    client = get_openmeteo_client()
    total = ingest_weather_history(con, client, LOCATIONS, start, end)
    return total


def main():
    con = get_connection(DEFAULT_DB_PATH)
    try:
        create_tables(con)

        logger.info("Starting backfill: %s → %s", START.date(), END.date())

        entsoe_client = get_entsoe_client()
        entsoe_total = backfill_entsoe_chunked(con, entsoe_client, START, END)
        logger.info("ENTSO-E total: %d rows", entsoe_total)

        weather_total = backfill_weather(con, START, END)
        logger.info("Weather total: %d rows", weather_total)

        logger.info("Backfill complete: %d total rows", entsoe_total + weather_total)
    finally:
        con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("backfill failed")
        sys.exit(1)
