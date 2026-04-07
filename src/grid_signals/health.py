"""Health check: verify data freshness across all tables."""

import logging
from datetime import UTC, datetime, timedelta

import psycopg
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_TABLES = ["day_ahead_prices", "generation_by_type", "total_load", "cross_border_flows"]


class TableHealth(BaseModel):
    """Freshness status of a single table."""

    table: str
    ok: bool
    latest: str | None = None
    age_hours: float | None = None


class HealthStatus(BaseModel):
    """Overall data health."""

    healthy: bool
    checks: list[TableHealth]


def check_data_freshness(
    con: psycopg.Connection,
    max_age_hours: int = 26,
) -> HealthStatus:
    """Verify that the latest data in each core table is within max_age_hours.

    Uses 26 hours by default to allow for a 2-hour ingestion window after
    the day-ahead market closes.
    """
    checks: list[TableHealth] = []
    all_ok = True

    for table in _TABLES:
        row = con.execute(f"SELECT MAX(period_start) FROM {table}").fetchone()
        latest = row[0] if row else None

        if latest is None:
            checks.append(TableHealth(table=table, ok=False))
            all_ok = False
            continue

        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=UTC)

        age = datetime.now(UTC) - latest
        ok = age < timedelta(hours=max_age_hours)
        checks.append(
            TableHealth(
                table=table,
                ok=ok,
                latest=latest.isoformat(),
                age_hours=round(age.total_seconds() / 3600, 1),
            )
        )
        if not ok:
            all_ok = False

    status = HealthStatus(healthy=all_ok, checks=checks)

    for check in checks:
        if check.ok:
            logger.info(
                "OK  %s: %s (%.1fh old)", check.table, check.latest, check.age_hours
            )
        else:
            logger.warning(
                "STALE %s: %s (%sh old)",
                check.table,
                check.latest or "no data",
                check.age_hours or "N/A",
            )

    return status
