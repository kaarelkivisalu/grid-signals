"""Pipeline orchestration: run ingestion jobs for ENTSO-E and Open-Meteo."""

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
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
from grid_signals.ingestion.openmeteo import (
    ingest_weather_forecasts,
    ingest_weather_history,
)
from grid_signals.ingestion.weather_client import get_openmeteo_client
from grid_signals.models.zones import BiddingZone

logger = logging.getLogger(__name__)


def run_daily(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Run daily ENTSO-E ingestion (yesterday 00:00 UTC to tomorrow 00:00 UTC).

    Covers both day-ahead data and actuals for the previous day.
    Returns total rows inserted.
    """
    today = pd.Timestamp.utcnow().normalize()
    start_ts = today - pd.Timedelta(days=1)
    end_ts = today + pd.Timedelta(days=1)

    zones = list(BiddingZone)

    con = get_connection(db_path)
    try:
        create_tables(con)
        client = get_entsoe_client()

        prices = ingest_day_ahead_prices(con, client, zones, start_ts, end_ts)
        logger.info("daily: day_ahead_prices → %d rows", prices)

        generation = ingest_generation_per_type(con, client, zones, start_ts, end_ts)
        logger.info("daily: generation → %d rows", generation)

        load = ingest_total_load(con, client, zones, start_ts, end_ts)
        logger.info("daily: total_load → %d rows", load)

        flows = ingest_cross_border_flows(con, client, BORDERS, start_ts, end_ts)
        logger.info("daily: cross_border_flows → %d rows", flows)

        outages = ingest_outages(con, client, zones, start_ts, end_ts)
        logger.info("daily: outages → %d rows", outages)

        total = prices + generation + load + flows + outages
        logger.info("daily: total → %d rows", total)
        return total
    finally:
        con.close()


def run_weather(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Run weather forecast ingestion (today to today + 7 days).

    Returns total rows inserted.
    """
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today
    end = today + timedelta(days=7)

    con = get_connection(db_path)
    try:
        create_tables(con)
        client = get_openmeteo_client()

        total = ingest_weather_forecasts(con, client, LOCATIONS, start, end)
        logger.info("weather: forecasts → %d rows", total)
        return total
    finally:
        con.close()


def run_backfill(
    db_path: Path = DEFAULT_DB_PATH,
    start: datetime | None = None,
    end: datetime | None = None,
) -> int:
    """Run backfill for both ENTSO-E and Open-Meteo over a date range.

    Returns total rows inserted.
    """
    if start is None or end is None:
        raise ValueError("start and end are required for backfill")

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    zones = list(BiddingZone)

    con = get_connection(db_path)
    try:
        create_tables(con)
        total = 0

        # ENTSO-E
        entsoe_client = get_entsoe_client()

        prices = ingest_day_ahead_prices(con, entsoe_client, zones, start_ts, end_ts)
        logger.info("backfill: day_ahead_prices → %d rows", prices)
        total += prices

        generation = ingest_generation_per_type(
            con, entsoe_client, zones, start_ts, end_ts
        )
        logger.info("backfill: generation → %d rows", generation)
        total += generation

        load = ingest_total_load(con, entsoe_client, zones, start_ts, end_ts)
        logger.info("backfill: total_load → %d rows", load)
        total += load

        flows = ingest_cross_border_flows(con, entsoe_client, BORDERS, start_ts, end_ts)
        logger.info("backfill: cross_border_flows → %d rows", flows)
        total += flows

        outages = ingest_outages(con, entsoe_client, zones, start_ts, end_ts)
        logger.info("backfill: outages → %d rows", outages)
        total += outages

        # Open-Meteo
        weather_client = get_openmeteo_client()

        weather = ingest_weather_history(con, weather_client, LOCATIONS, start, end)
        logger.info("backfill: weather_history → %d rows", weather)
        total += weather

        logger.info("backfill: total → %d rows", total)
        return total
    finally:
        con.close()


def _date_ranges(dates: list[date]) -> list[tuple[date, date]]:
    """Collapse a sorted list of dates into (start, end_exclusive) ranges."""
    if not dates:
        return []
    ranges: list[tuple[date, date]] = []
    range_start = dates[0]
    prev = dates[0]
    for d in dates[1:]:
        if d == prev + timedelta(days=1):
            prev = d
        else:
            ranges.append((range_start, prev + timedelta(days=1)))
            range_start = d
            prev = d
    ranges.append((range_start, prev + timedelta(days=1)))
    return ranges


def run_backfill_gaps(
    db_path: Path = DEFAULT_DB_PATH,
    start: datetime | None = None,
    end: datetime | None = None,
) -> int:
    """Detect gaps and backfill only the missing data.

    Returns total rows inserted.
    """
    if start is None or end is None:
        raise ValueError("start and end are required for gap backfill")

    from grid_signals.validation import find_gaps

    con = get_connection(db_path)
    try:
        create_tables(con)

        gaps = find_gaps(con, start, end)
        logger.info("gap detection:\n%s", gaps.summary())

        if gaps.empty:
            logger.info("backfill-gaps: nothing to do")
            return 0

        total = 0
        entsoe_client = get_entsoe_client()

        # Prices
        for zone_val, missing in gaps.prices.items():
            zone = BiddingZone(zone_val)
            for rng_start, rng_end in _date_ranges(missing):
                s = pd.Timestamp(datetime.combine(rng_start, datetime.min.time(), tzinfo=UTC))
                e = pd.Timestamp(datetime.combine(rng_end, datetime.min.time(), tzinfo=UTC))
                rows = ingest_day_ahead_prices(con, entsoe_client, [zone], s, e)
                logger.info("backfill-gaps: prices %s %s→%s → %d rows", zone, rng_start, rng_end, rows)
                total += rows

        # Generation
        for zone_val, missing in gaps.generation.items():
            zone = BiddingZone(zone_val)
            for rng_start, rng_end in _date_ranges(missing):
                s = pd.Timestamp(datetime.combine(rng_start, datetime.min.time(), tzinfo=UTC))
                e = pd.Timestamp(datetime.combine(rng_end, datetime.min.time(), tzinfo=UTC))
                rows = ingest_generation_per_type(con, entsoe_client, [zone], s, e)
                logger.info("backfill-gaps: generation %s %s→%s → %d rows", zone, rng_start, rng_end, rows)
                total += rows

        # Load
        for zone_val, missing in gaps.load.items():
            zone = BiddingZone(zone_val)
            for rng_start, rng_end in _date_ranges(missing):
                s = pd.Timestamp(datetime.combine(rng_start, datetime.min.time(), tzinfo=UTC))
                e = pd.Timestamp(datetime.combine(rng_end, datetime.min.time(), tzinfo=UTC))
                rows = ingest_total_load(con, entsoe_client, [zone], s, e)
                logger.info("backfill-gaps: load %s %s→%s → %d rows", zone, rng_start, rng_end, rows)
                total += rows

        # Flows
        for border_key, missing in gaps.flows.items():
            from_z, to_z = border_key.split("→")
            for rng_start, rng_end in _date_ranges(missing):
                s = pd.Timestamp(datetime.combine(rng_start, datetime.min.time(), tzinfo=UTC))
                e = pd.Timestamp(datetime.combine(rng_end, datetime.min.time(), tzinfo=UTC))
                rows = ingest_cross_border_flows(con, entsoe_client, [(from_z, to_z)], s, e)
                logger.info("backfill-gaps: flows %s→%s %s→%s → %d rows", from_z, to_z, rng_start, rng_end, rows)
                total += rows

        # Weather gaps (Open-Meteo)
        weather_client = get_openmeteo_client()
        weather_gaps = _find_weather_gaps(con, start, end)
        for loc_name, missing in weather_gaps.items():
            loc = next((loc_ for loc_ in LOCATIONS if loc_.name == loc_name), None)
            if loc is None:
                continue
            for rng_start, rng_end in _date_ranges(missing):
                s = datetime.combine(rng_start, datetime.min.time(), tzinfo=UTC)
                e = datetime.combine(rng_end, datetime.min.time(), tzinfo=UTC)
                rows = ingest_weather_history(con, weather_client, [loc], s, e)
                logger.info("backfill-gaps: weather %s %s→%s → %d rows", loc_name, rng_start, rng_end, rows)
                total += rows

        logger.info("backfill-gaps: total → %d rows", total)
        return total
    finally:
        con.close()


def _find_weather_gaps(
    con: duckdb.DuckDBPyConnection,
    start: datetime,
    end: datetime,
) -> dict[str, list[date]]:
    """Find locations with missing weather data for dates in [start, end)."""
    from collections import defaultdict

    from grid_signals.validation import _expected_dates

    rows = con.execute(
        """
        SELECT location_name, CAST(period_start AS DATE) AS d
        FROM weather_forecasts
        WHERE period_start >= ? AND period_start < ?
        GROUP BY location_name, d
        """,
        [start, end],
    ).fetchall()

    present: dict[str, set[date]] = defaultdict(set)
    for loc, d in rows:
        present[loc].add(d)

    expected = _expected_dates(start, end)
    gaps: dict[str, list[date]] = {}
    for loc in LOCATIONS:
        missing = sorted(expected - present.get(loc.name, set()))
        if missing:
            gaps[loc.name] = missing
    return gaps
