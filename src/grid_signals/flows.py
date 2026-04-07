"""Prefect flows wrapping existing pipeline functions."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

from prefect import flow, task

logger = logging.getLogger(__name__)

# DATABASE_URL is passed via environment; no file path needed.
_DSN: str | None = os.environ.get("DATABASE_URL")
_APP_DIR_STR: str | None = os.environ.get("APP_DIR")
_RESOLVED_BRIEFINGS_DIR = (
    __import__("pathlib").Path(_APP_DIR_STR) / "briefings" if _APP_DIR_STR else None
)


def _setup_library_logging() -> None:
    """Ensure grid_signals loggers emit at INFO inside Prefect runs.

    PREFECT_LOGGING_EXTRA_LOGGERS attaches the API handler but leaves
    the level at NOTSET, so the effective level falls back to the root
    logger's WARNING.  Explicitly lowering it to INFO lets pipeline /
    ingestion logs reach the Prefect UI.
    """
    lib_logger = logging.getLogger("grid_signals")
    lib_logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@task(retries=2, retry_delay_seconds=60, timeout_seconds=600)
def ingest_daily(dsn: str | None = _DSN) -> int:
    """Pull day-ahead prices, generation, load, outages, and flows."""
    from grid_signals.pipeline import run_daily

    return run_daily(dsn)


@task(retries=2, retry_delay_seconds=30, timeout_seconds=300)
def ingest_weather(dsn: str | None = _DSN) -> int:
    """Update 7-day weather forecasts for all locations."""
    from grid_signals.pipeline import run_weather

    return run_weather(dsn)


@task(retries=1, retry_delay_seconds=60, timeout_seconds=600)
def backfill_gaps(dsn: str | None, start: datetime, end: datetime) -> int:
    """Detect and fill missing data for the given date range."""
    from grid_signals.pipeline import run_backfill_gaps

    return run_backfill_gaps(dsn, start, end)


@task(timeout_seconds=120)
def validate_data(dsn: str | None = _DSN) -> int:
    """Run all data quality checks. Returns number of failures."""
    from grid_signals.db.connection import get_connection
    from grid_signals.db.schema import create_tables
    from grid_signals.validation import run_all_validations

    con = get_connection(dsn)
    try:
        create_tables(con)
        results = run_all_validations(con)
        return sum(1 for r in results if not r.passed)
    finally:
        con.close()


@task(retries=1, retry_delay_seconds=30, timeout_seconds=300)
def backup_db(
    dsn: str | None, s3_bucket: str, prefix: str = "grid-signals/backups"
) -> str:
    """Backup the database to S3."""
    from grid_signals.backup import backup_database

    return backup_database(dsn, s3_bucket=s3_bucket, prefix=prefix)


@task(timeout_seconds=60)
def health_check(dsn: str | None = _DSN, max_age_hours: int = 26) -> bool:
    """Check data freshness. Returns True if healthy."""
    from grid_signals.db.connection import get_connection
    from grid_signals.health import check_data_freshness

    con = get_connection(dsn, read_only=True)
    try:
        status = check_data_freshness(con, max_age_hours=max_age_hours)
        return status.healthy
    finally:
        con.close()


@task(retries=1, retry_delay_seconds=30, timeout_seconds=600)
def generate_briefing(dsn: str | None = _DSN) -> str:
    """Generate the morning briefing. Returns briefing content."""
    from grid_signals.briefing import generate_briefing as _generate
    from grid_signals.db.connection import get_connection
    from grid_signals.db.schema import create_tables

    con = get_connection(dsn)
    try:
        create_tables(con)
        kwargs: dict = {"validate_first": False}
        if _RESOLVED_BRIEFINGS_DIR is not None:
            kwargs["output_dir"] = _RESOLVED_BRIEFINGS_DIR
        result = _generate(con, **kwargs)  # validation runs as separate task
        return result.content
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


@flow(name="morning-pipeline", log_prints=True)
def morning_pipeline(
    dsn: str | None = _DSN,
    s3_bucket: str | None = None,
) -> None:
    """Full morning pipeline: ingest → backfill → validate → briefing → backup → health."""
    if s3_bucket is None:
        s3_bucket = os.environ.get("S3_BUCKET") or None

    _setup_library_logging()
    rows = ingest_daily(dsn)
    logger.info("Daily ingestion: %d rows", rows)

    now = datetime.now(UTC)
    start = (now - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    gap_rows = backfill_gaps(dsn, start, end)
    logger.info("Gap backfill: %d rows", gap_rows)

    failures = validate_data(dsn)
    if failures:
        logger.warning("Validation: %d failures", failures)

    briefing = generate_briefing(dsn)
    logger.info("Briefing generated: %d chars", len(briefing))

    if s3_bucket:
        backup_db(dsn, s3_bucket)

    healthy = health_check(dsn)
    if not healthy:
        logger.warning("Health check: some tables have stale data")


@flow(name="weather-update", log_prints=True)
def weather_update(dsn: str | None = _DSN) -> None:
    """Weather forecast update flow."""
    _setup_library_logging()
    rows = ingest_weather(dsn)
    logger.info("Weather update: %d rows", rows)


@task(retries=2, retry_delay_seconds=120, timeout_seconds=3600)
def backfill_chunk(
    dsn: str | None, start: datetime, end: datetime, chunk_label: str
) -> int:
    """Backfill a single date range chunk."""
    from grid_signals.pipeline import run_backfill

    logger.info("Backfill chunk %s: %s → %s", chunk_label, start, end)
    return run_backfill(dsn, start, end)


@flow(name="initial-seed", log_prints=True, timeout_seconds=7200)
def initial_seed(
    dsn: str | None = _DSN,
    days: int = 90,
) -> None:
    """One-time data seed: backfill historical data and weather, then validate.

    Run this manually after first deploy to populate the database.
    Splits the backfill into 30-day chunks to stay within ENTSO-E rate limits
    and avoid timeouts.
    """
    _setup_library_logging()

    now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now + timedelta(days=1)
    start = now - timedelta(days=days)

    # Split into 30-day chunks
    chunk_start = start
    chunk_num = 0
    total_rows = 0
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=30), end)
        chunk_num += 1
        rows = backfill_chunk(dsn, chunk_start, chunk_end, f"{chunk_num}")
        total_rows += rows
        chunk_start = chunk_end

    logger.info(
        "Backfill complete: %d total rows across %d chunks", total_rows, chunk_num
    )

    # Weather forecasts (next 7 days)
    weather_rows = ingest_weather(dsn)
    logger.info("Weather seed: %d rows", weather_rows)

    # Validate
    failures = validate_data(dsn)
    if failures:
        logger.warning("Validation: %d failures after seed", failures)
    else:
        logger.info("Validation: all checks passed")
