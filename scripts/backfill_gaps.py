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


def _get_missing_ranges(con, table, ts_col, start, end):
    """Return list of (start, end) datetime pairs covering days with no data."""
    existing_dates = {
        row[0]
        for row in con.execute(
            f"SELECT DISTINCT CAST({ts_col} AS DATE) FROM {table}"
            f" WHERE {ts_col} >= ? AND {ts_col} < ?",
            [start, end],
        ).fetchall()
    }

    missing_days = []
    current = start
    while current < end:
        if current.date() not in existing_dates:
            missing_days.append(current)
        current += timedelta(days=1)

    if not missing_days:
        return []

    # Merge consecutive missing days into contiguous ranges, then cap at CHUNK_DAYS
    ranges = []
    range_start = missing_days[0]
    prev = missing_days[0]
    for day in missing_days[1:]:
        if day - prev > timedelta(days=1):
            ranges.extend(_split(range_start, prev + timedelta(days=1)))
            range_start = day
        prev = day
    ranges.extend(_split(range_start, prev + timedelta(days=1)))
    return ranges


def _split(start, end):
    """Split a date range into CHUNK_DAYS-sized pieces."""
    chunks = []
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=CHUNK_DAYS), end)
        chunks.append((current, chunk_end))
        current = chunk_end
    return chunks


def backfill_entsoe_chunked(con, client, start, end):
    """Backfill ENTSO-E data, fetching only date ranges missing from the DB."""
    total = 0
    tasks = [
        (
            "prices",
            "day_ahead_prices",
            "timestamp",
            lambda s, e: ingest_day_ahead_prices(con, client, zones, s, e),
        ),
        (
            "generation",
            "generation_by_type",
            "timestamp",
            lambda s, e: ingest_generation_per_type(con, client, zones, s, e),
        ),
        (
            "load",
            "total_load",
            "timestamp",
            lambda s, e: ingest_total_load(con, client, zones, s, e),
        ),
        (
            "flows",
            "cross_border_flows",
            "timestamp",
            lambda s, e: ingest_cross_border_flows(con, client, BORDERS, s, e),
        ),
        (
            "outages",
            "outages",
            "start_time",
            lambda s, e: ingest_outages(con, client, zones, s, e),
        ),
    ]
    for label, table, ts_col, ingest_fn in tasks:
        ranges = _get_missing_ranges(con, table, ts_col, start, end)
        if not ranges:
            logger.info("%s: fully covered, skipping", label)
            continue
        for r_start, r_end in ranges:
            s, e = pd.Timestamp(r_start), pd.Timestamp(r_end)
            n = ingest_fn(s, e)
            logger.info("  %s %s → %s: %d rows", label, r_start.date(), r_end.date(), n)
            total += n
    return total


def backfill_weather(con, start, end):
    """Backfill weather history, fetching only date ranges missing from the DB."""
    client = get_openmeteo_client()
    ranges = _get_missing_ranges(con, "weather_forecasts", "timestamp", start, end)
    if not ranges:
        logger.info("weather: fully covered, skipping")
        return 0
    total = 0
    for r_start, r_end in ranges:
        n = ingest_weather_history(con, client, LOCATIONS, r_start, r_end)
        logger.info("  weather %s → %s: %d rows", r_start.date(), r_end.date(), n)
        total += n
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
