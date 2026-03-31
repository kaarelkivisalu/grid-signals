"""Pipeline orchestration: run ingestion jobs for ENTSO-E and Open-Meteo."""

import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd
from entsoe.exceptions import NoMatchingDataError

from grid_signals.db.connection import DEFAULT_DB_PATH, get_connection
from grid_signals.db.schema import create_tables
from grid_signals.db.queries import (
    insert_cross_border_flows,
    insert_day_ahead_prices,
    insert_generation_by_type,
    insert_outages,
    insert_total_load,
)
from grid_signals.ingestion.client import BORDERS, get_entsoe_client
from grid_signals.ingestion.entsoe import (
    fetch_cross_border_flows,
    fetch_day_ahead_prices,
    fetch_generation,
    fetch_load_actual,
    fetch_load_forecast,
    fetch_outages,
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
from grid_signals.ingestion.rate_limiter import RateLimiter
from grid_signals.ingestion.weather_client import get_openmeteo_client
from grid_signals.models.zones import BiddingZone

logger = logging.getLogger(__name__)

# ENTSO-E allows 400 req/min.  6 req/s = 360/min leaves headroom for retries.
_ENTSOE_MAX_PER_SECOND = 6.0
_ENTSOE_MAX_WORKERS = 8


# ---------------------------------------------------------------------------
# Parallel ENTSO-E helper
# ---------------------------------------------------------------------------


def _parallel_entsoe_ingest(
    con: duckdb.DuckDBPyConnection,
    zones: list[BiddingZone],
    borders: list[tuple[str, str]],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    max_workers: int = _ENTSOE_MAX_WORKERS,
) -> int:
    """Fetch all ENTSO-E data in parallel, write to DB sequentially.

    Creates one ENTSO-E client per worker thread (requests.Session is not
    thread-safe) and rate-limits API calls to stay under 400 req/min.
    """
    limiter = RateLimiter(max_per_second=_ENTSOE_MAX_PER_SECOND)
    local = threading.local()

    def _get_client():
        if not hasattr(local, "client"):
            local.client = get_entsoe_client()
        return local.client

    # Build task list: (label, fetch_callable, insert_fn)
    tasks: list[tuple[str, Callable[[], list[Any]], Callable]] = []

    for zone in zones:
        tasks.append((
            f"prices/{zone.value}",
            lambda z=zone: fetch_day_ahead_prices(_get_client(), z, start, end, limiter),
            insert_day_ahead_prices,
        ))
        tasks.append((
            f"generation/{zone.value}",
            lambda z=zone: fetch_generation(_get_client(), z, start, end, limiter),
            insert_generation_by_type,
        ))
        tasks.append((
            f"load_actual/{zone.value}",
            lambda z=zone: fetch_load_actual(_get_client(), z, start, end, limiter),
            insert_total_load,
        ))
        tasks.append((
            f"load_forecast/{zone.value}",
            lambda z=zone: fetch_load_forecast(_get_client(), z, start, end, limiter),
            insert_total_load,
        ))
        tasks.append((
            f"outages/{zone.value}",
            lambda z=zone: fetch_outages(_get_client(), z, start, end, limiter),
            insert_outages,
        ))

    for from_zone, to_zone in borders:
        tasks.append((
            f"flows/{from_zone}→{to_zone}",
            lambda f=from_zone, t=to_zone: fetch_cross_border_flows(
                _get_client(), f, t, start, end, limiter,
            ),
            insert_cross_border_flows,
        ))

    # Phase 1: fetch in parallel
    num_tasks = len(tasks)
    logger.info("ENTSO-E fetch: starting %d tasks with %d workers", num_tasks, max_workers)
    results: list[tuple[str, Callable, list[Any]]] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_meta = {
            pool.submit(fetch_fn): (label, insert_fn)
            for label, fetch_fn, insert_fn in tasks
        }
        for future in as_completed(future_to_meta):
            label, insert_fn = future_to_meta[future]
            completed += 1
            try:
                rows = future.result()
                if rows:
                    results.append((label, insert_fn, rows))
                    logger.info("[%d/%d] %s: fetched %d rows", completed, num_tasks, label, len(rows))
                else:
                    logger.info("[%d/%d] %s: empty result", completed, num_tasks, label)
            except NoMatchingDataError:
                logger.warning("[%d/%d] %s: no data", completed, num_tasks, label)
            except Exception:
                logger.error("[%d/%d] %s: error\n%s", completed, num_tasks, label, traceback.format_exc())

    logger.info("ENTSO-E fetch complete: %d/%d tasks returned data", len(results), num_tasks)

    # Phase 2: write sequentially (DuckDB single-writer lock)
    total = 0
    for i, (label, insert_fn, rows) in enumerate(results, 1):
        count = insert_fn(con, rows)
        total += count
        logger.info("[%d/%d] %s: inserted %d rows", i, len(results), label, count)
    logger.info("ENTSO-E insert complete: %d total rows", total)
    return total


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
        total = _parallel_entsoe_ingest(con, zones, BORDERS, start_ts, end_ts)
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

        # ENTSO-E (parallel)
        total += _parallel_entsoe_ingest(con, zones, BORDERS, start_ts, end_ts)

        # Open-Meteo (sequential — free API, no parallelism needed)
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
