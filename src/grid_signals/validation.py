"""Data quality checks for ingested energy and weather data."""

import logging
from datetime import UTC, datetime, timedelta

import duckdb
from pydantic import BaseModel

from grid_signals.ingestion.locations import LOCATIONS
from grid_signals.models.zones import BiddingZone

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    """Outcome of a single data quality check."""

    check: str
    passed: bool
    detail: str


def validate_price_completeness(
    con: duckdb.DuckDBPyConnection,
    zone: BiddingZone,
    date: datetime,
) -> list[ValidationResult]:
    """Check that 24 hourly prices exist for the given zone and date.

    Accepts 23 or 25 hours to account for DST transitions.
    """
    start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    row = con.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM day_ahead_prices
        WHERE zone = ? AND timestamp >= ? AND timestamp < ?
        """,
        [zone.value, start, end],
    ).fetchone()
    count = row[0] if row else 0

    passed = count in (23, 24, 25)
    return [
        ValidationResult(
            check=f"price_completeness:{zone.value}",
            passed=passed,
            detail=f"{count} hours found (expected 23-25)",
        )
    ]


def validate_price_bounds(
    con: duckdb.DuckDBPyConnection,
    zone: BiddingZone,
    date: datetime,
) -> list[ValidationResult]:
    """Flag prices outside the -500 to 4000 EUR/MWh range."""
    start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    row = con.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM day_ahead_prices
        WHERE zone = ? AND timestamp >= ? AND timestamp < ?
          AND (price_eur_mwh < -500 OR price_eur_mwh > 4000)
        """,
        [zone.value, start, end],
    ).fetchone()
    outliers = row[0] if row else 0

    passed = outliers == 0
    return [
        ValidationResult(
            check=f"price_bounds:{zone.value}",
            passed=passed,
            detail=f"{outliers} prices outside [-500, 4000] EUR/MWh",
        )
    ]


def validate_weather_freshness(
    con: duckdb.DuckDBPyConnection,
    location: str,
    max_age_hours: int = 12,
) -> list[ValidationResult]:
    """Check that the latest weather forecast is recent enough."""
    row = con.execute(
        """
        SELECT MAX(fetched_at) AS latest
        FROM weather_forecasts
        WHERE location_name = ?
        """,
        [location],
    ).fetchone()
    latest = row[0] if row else None

    if latest is None:
        return [
            ValidationResult(
                check=f"weather_freshness:{location}",
                passed=False,
                detail="no weather data found",
            )
        ]

    # DuckDB may return a datetime without tzinfo; treat as UTC
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)

    age = datetime.now(UTC) - latest
    passed = age <= timedelta(hours=max_age_hours)
    hours_ago = age.total_seconds() / 3600
    return [
        ValidationResult(
            check=f"weather_freshness:{location}",
            passed=passed,
            detail=f"latest forecast is {hours_ago:.1f}h old (max {max_age_hours}h)",
        )
    ]


def run_all_validations(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Run all validation checks for yesterday's data across all zones/locations."""
    yesterday = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=1)

    results: list[ValidationResult] = []

    for zone in BiddingZone:
        results.extend(validate_price_completeness(con, zone, yesterday))
        results.extend(validate_price_bounds(con, zone, yesterday))

    for loc in LOCATIONS:
        results.extend(validate_weather_freshness(con, loc.name))

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    logger.info("validation: %d passed, %d failed out of %d checks", passed, failed, len(results))

    for r in results:
        if not r.passed:
            logger.warning("FAIL %s: %s", r.check, r.detail)

    return results
