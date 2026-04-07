"""Data quality checks for ingested energy and weather data."""

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

import psycopg
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
    con: psycopg.Connection,
    zone: BiddingZone,
    date: datetime,
) -> list[ValidationResult]:
    """Check that prices cover the full day for the given zone.

    Detects resolution (hourly or 15-min) directly from period_end - period_start.
    Expects:
    - Hourly (60 min): 23-25 intervals (DST transitions)
    - Quarter-hourly (15 min): 92-100 intervals (DST transitions)
    """
    start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    total_rows_row = con.execute(
        "SELECT COUNT(*) FROM day_ahead_prices WHERE zone = %s AND period_start >= %s AND period_start < %s",
        [zone.value, start, end],
    ).fetchone()
    count = total_rows_row[0] if total_rows_row else 0

    if count == 0:
        return [
            ValidationResult(
                check=f"price_completeness:{zone.value}",
                passed=False,
                detail="0 intervals found",
            )
        ]

    # Detect resolution from the period duration
    interval_row = con.execute(
        """
        SELECT MIN((EXTRACT(EPOCH FROM (period_end - period_start)) / 60)::INT) AS min_interval_min
        FROM day_ahead_prices
        WHERE zone = %s AND period_start >= %s AND period_start < %s
        """,
        [zone.value, start, end],
    ).fetchone()
    min_interval = (
        interval_row[0] if interval_row and interval_row[0] is not None else 60
    )

    if min_interval <= 15:
        resolution = "15min"
        expected_min, expected_max = 92, 100
    else:
        resolution = "hourly"
        expected_min, expected_max = 23, 25

    passed = expected_min <= count <= expected_max
    return [
        ValidationResult(
            check=f"price_completeness:{zone.value}",
            passed=passed,
            detail=f"{count} intervals ({resolution}), expected {expected_min}-{expected_max}",
        )
    ]


def validate_price_bounds(
    con: psycopg.Connection,
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
        WHERE zone = %s AND period_start >= %s AND period_start < %s
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
    con: psycopg.Connection,
    location: str,
    max_age_hours: int = 12,
) -> list[ValidationResult]:
    """Check that the latest weather forecast is recent enough."""
    row = con.execute(
        """
        SELECT MAX(fetched_at) AS latest
        FROM weather_forecasts
        WHERE location_name = %s
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


def run_all_validations(
    con: psycopg.Connection,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[ValidationResult]:
    """Run all validation checks across all zones/locations.

    If *start*/*end* are omitted the check covers yesterday only.
    When a range is given, price checks run for every day in [start, end).
    Weather freshness is always checked once (it's point-in-time).
    """
    if start is None:
        start = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
    if end is None:
        end = start + timedelta(days=1)

    results: list[ValidationResult] = []

    # Iterate over each day in the range
    day = start
    while day < end:
        for zone in BiddingZone:
            results.extend(validate_price_completeness(con, zone, day))
            results.extend(validate_price_bounds(con, zone, day))
        day += timedelta(days=1)

    for loc in LOCATIONS:
        results.extend(validate_weather_freshness(con, loc.name))

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    logger.info(
        "validation: %d passed, %d failed out of %d checks",
        passed,
        failed,
        len(results),
    )

    for r in results:
        if not r.passed:
            logger.warning("FAIL %s: %s", r.check, r.detail)

    return results


# ---------------------------------------------------------------------------
# Gap detection — find missing data across all tables
# ---------------------------------------------------------------------------


class DataGaps(BaseModel):
    """Missing data detected across tables."""

    prices: dict[str, list[date]]  # zone → missing dates
    generation: dict[str, list[date]]
    load: dict[str, list[date]]
    flows: dict[str, list[date]]  # "FROM→TO" → missing dates

    @property
    def empty(self) -> bool:
        return not (self.prices or self.generation or self.load or self.flows)

    def summary(self) -> str:
        lines: list[str] = []
        for label, gaps in [
            ("prices", self.prices),
            ("generation", self.generation),
            ("load", self.load),
            ("flows", self.flows),
        ]:
            if gaps:
                total_days = sum(len(d) for d in gaps.values())
                lines.append(
                    f"  {label}: {len(gaps)} zone(s), {total_days} missing day(s)"
                )
        if not lines:
            return "No gaps found."
        return "Gaps detected:\n" + "\n".join(lines)


def _expected_dates(start: datetime, end: datetime) -> set[date]:
    """Return the set of dates in [start, end)."""
    dates: set[date] = set()
    d = start.date() if isinstance(start, datetime) else start
    end_d = end.date() if isinstance(end, datetime) else end
    while d < end_d:
        dates.add(d)
        d += timedelta(days=1)
    return dates


def _find_zone_date_gaps(
    con: psycopg.Connection,
    table: str,
    zones: list[BiddingZone],
    start: datetime,
    end: datetime,
) -> dict[str, list[date]]:
    """Find (zone, date) pairs with zero rows in *table*."""
    rows = con.execute(
        f"""
        SELECT zone, CAST(period_start AS DATE) AS d
        FROM {table}
        WHERE period_start >= %s AND period_start < %s
        GROUP BY zone, d
        """,
        [start, end],
    ).fetchall()

    present: dict[str, set[date]] = defaultdict(set)
    for zone_val, d in rows:
        present[zone_val].add(d)

    expected = _expected_dates(start, end)
    gaps: dict[str, list[date]] = {}
    for zone in zones:
        missing = sorted(expected - present.get(zone.value, set()))
        if missing:
            gaps[zone.value] = missing
    return gaps


def _find_flow_gaps(
    con: psycopg.Connection,
    borders: list[tuple[str, str]],
    start: datetime,
    end: datetime,
) -> dict[str, list[date]]:
    """Find (border, date) pairs with zero rows in cross_border_flows."""
    rows = con.execute(
        """
        SELECT from_zone, to_zone, CAST(period_start AS DATE) AS d
        FROM cross_border_flows
        WHERE period_start >= %s AND period_start < %s
        GROUP BY from_zone, to_zone, d
        """,
        [start, end],
    ).fetchall()

    present: dict[str, set[date]] = defaultdict(set)
    for fz, tz, d in rows:
        present[f"{fz}→{tz}"].add(d)

    expected = _expected_dates(start, end)
    gaps: dict[str, list[date]] = {}
    for from_zone, to_zone in borders:
        key = f"{from_zone}→{to_zone}"
        missing = sorted(expected - present.get(key, set()))
        if missing:
            gaps[key] = missing
    return gaps


def find_gaps(
    con: psycopg.Connection,
    start: datetime,
    end: datetime,
    borders: list[tuple[str, str]] | None = None,
) -> DataGaps:
    """Detect missing data across all tables for the given date range.

    *borders* defaults to the full BORDERS list from ingestion.client.
    """
    if borders is None:
        from grid_signals.ingestion.client import BORDERS

        borders = BORDERS

    zones = list(BiddingZone)
    return DataGaps(
        prices=_find_zone_date_gaps(con, "day_ahead_prices", zones, start, end),
        generation=_find_zone_date_gaps(con, "generation_by_type", zones, start, end),
        load=_find_zone_date_gaps(con, "total_load", zones, start, end),
        flows=_find_flow_gaps(con, borders, start, end),
    )
