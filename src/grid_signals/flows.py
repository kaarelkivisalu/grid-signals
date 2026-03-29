"""Prefect flows wrapping existing pipeline functions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from prefect import flow, task

from grid_signals.db.connection import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@task(retries=2, retry_delay_seconds=60, timeout_seconds=600)
def ingest_daily(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Pull day-ahead prices, generation, load, outages, and flows."""
    from grid_signals.pipeline import run_daily

    return run_daily(db_path)


@task(retries=2, retry_delay_seconds=30, timeout_seconds=300)
def ingest_weather(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Update 7-day weather forecasts for all locations."""
    from grid_signals.pipeline import run_weather

    return run_weather(db_path)


@task(retries=1, retry_delay_seconds=60, timeout_seconds=600)
def backfill_gaps(db_path: Path, start: datetime, end: datetime) -> int:
    """Detect and fill missing data for the given date range."""
    from grid_signals.pipeline import run_backfill_gaps

    return run_backfill_gaps(db_path, start, end)


@task(timeout_seconds=120)
def validate_data(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Run all data quality checks. Returns number of failures."""
    from grid_signals.db.connection import get_connection
    from grid_signals.db.schema import create_tables
    from grid_signals.validation import run_all_validations

    con = get_connection(db_path)
    try:
        create_tables(con)
        results = run_all_validations(con)
        return sum(1 for r in results if not r.passed)
    finally:
        con.close()


@task(retries=1, retry_delay_seconds=30, timeout_seconds=300)
def backup_db(db_path: Path, s3_bucket: str, prefix: str = "grid-signals/backups") -> str:
    """Backup the DuckDB database to S3."""
    from grid_signals.backup import backup_database

    return backup_database(db_path, s3_bucket=s3_bucket, prefix=prefix)


@task(timeout_seconds=60)
def health_check(db_path: Path = DEFAULT_DB_PATH, max_age_hours: int = 26) -> bool:
    """Check data freshness. Returns True if healthy."""
    from grid_signals.db.connection import get_connection
    from grid_signals.db.schema import create_tables
    from grid_signals.health import check_data_freshness

    con = get_connection(db_path, read_only=True)
    try:
        create_tables(con)
        status = check_data_freshness(con, max_age_hours=max_age_hours)
        return status.healthy
    finally:
        con.close()


@task(retries=1, retry_delay_seconds=30, timeout_seconds=600)
def generate_briefing(db_path: Path = DEFAULT_DB_PATH) -> str:
    """Generate the morning briefing. Returns briefing content."""
    from grid_signals.briefing import generate_briefing as _generate

    from grid_signals.db.connection import get_connection
    from grid_signals.db.schema import create_tables

    con = get_connection(db_path)
    try:
        create_tables(con)
        result = _generate(con, validate_first=False)  # validation runs as separate task
        return result.content
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


@flow(name="morning-pipeline", log_prints=True)
def morning_pipeline(
    db_path: Path = DEFAULT_DB_PATH,
    s3_bucket: str | None = None,
) -> None:
    """Full morning pipeline: ingest → backfill → validate → briefing → backup → health.

    Tasks run sequentially because DuckDB has a single-writer lock.
    """
    rows = ingest_daily(db_path)
    logger.info("Daily ingestion: %d rows", rows)

    now = datetime.now(UTC)
    start = (now - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    gap_rows = backfill_gaps(db_path, start, end)
    logger.info("Gap backfill: %d rows", gap_rows)

    failures = validate_data(db_path)
    if failures:
        logger.warning("Validation: %d failures", failures)

    briefing = generate_briefing(db_path)
    logger.info("Briefing generated: %d chars", len(briefing))

    if s3_bucket:
        backup_db(db_path, s3_bucket)

    healthy = health_check(db_path)
    if not healthy:
        logger.warning("Health check: some tables have stale data")


@flow(name="weather-update", log_prints=True)
def weather_update(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Weather forecast update flow."""
    rows = ingest_weather(db_path)
    logger.info("Weather update: %d rows", rows)
