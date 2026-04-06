"""Orchestrator functions: fetch from ENTSO-E, transform, insert into DuckDB.

The ``fetch_*`` functions handle API calls and transformation only (no DB
writes) so they can be called from multiple threads.  The ``ingest_*``
functions combine fetch + insert and are kept for sequential / gap-backfill
use.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from time import sleep
from typing import TYPE_CHECKING, TypeVar

import duckdb
import pandas as pd
import requests.exceptions
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError

from grid_signals.db.queries import (
    insert_cross_border_flows,
    insert_day_ahead_prices,
    insert_generation_by_type,
    insert_outages,
    insert_total_load,
)
from grid_signals.ingestion.client import ZONE_TO_ENTSOE
from grid_signals.ingestion.transformers import (
    transform_cross_border_flows,
    transform_day_ahead_prices,
    transform_generation,
    transform_load,
    transform_outages,
)
from grid_signals.models.zones import BiddingZone

if TYPE_CHECKING:
    from grid_signals.ingestion.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_RETRIES = 3
_INITIAL_DELAY = 5  # seconds


def _retry_on_server_error(fn: Callable[..., T], *args, **kwargs) -> T:
    """Call *fn* with retries on transient HTTP 5xx errors.

    Uses exponential back-off (5 s, 10 s, 20 s).  Non-5xx errors and
    non-HTTP exceptions propagate immediately.
    """
    delay = _INITIAL_DELAY
    last_exc: requests.exceptions.HTTPError | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code >= 500:
                last_exc = exc
                logger.warning(
                    "HTTP %s – retrying in %ds (attempt %d/%d)",
                    exc.response.status_code,
                    delay,
                    attempt,
                    _MAX_RETRIES,
                )
                sleep(delay)
                delay *= 2
            else:
                raise
    raise last_exc  # type: ignore[misc]


def ingest_day_ahead_prices(
    con: duckdb.DuckDBPyConnection,
    client: EntsoePandasClient,
    zones: list[BiddingZone],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> int:
    """Fetch and store day-ahead prices for the given zones."""
    total = 0
    for zone in zones:
        try:
            series = _retry_on_server_error(
                client.query_day_ahead_prices,
                ZONE_TO_ENTSOE[zone],
                start=start,
                end=end,
            )
            rows = transform_day_ahead_prices(series, zone)
            total += insert_day_ahead_prices(con, rows)
            logger.info("day_ahead_prices: %s → %d rows", zone, len(rows))
        except NoMatchingDataError:
            logger.warning("day_ahead_prices: no data for %s", zone)
        except Exception:
            logger.error(
                "day_ahead_prices: error for %s\n%s", zone, traceback.format_exc()
            )
    return total


def ingest_generation_per_type(
    con: duckdb.DuckDBPyConnection,
    client: EntsoePandasClient,
    zones: list[BiddingZone],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> int:
    """Fetch and store generation per type for the given zones."""
    total = 0
    for zone in zones:
        try:
            df = _retry_on_server_error(
                client.query_generation,
                ZONE_TO_ENTSOE[zone],
                start=start,
                end=end,
            )
            rows = transform_generation(df, zone)
            total += insert_generation_by_type(con, rows)
            logger.info("generation: %s → %d rows", zone, len(rows))
        except NoMatchingDataError:
            logger.warning("generation: no data for %s", zone)
        except Exception:
            logger.error("generation: error for %s\n%s", zone, traceback.format_exc())
    return total


def ingest_total_load(
    con: duckdb.DuckDBPyConnection,
    client: EntsoePandasClient,
    zones: list[BiddingZone],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> int:
    """Fetch and store actual load and load forecast for the given zones."""
    total = 0
    for zone in zones:
        entsoe_zone = ZONE_TO_ENTSOE[zone]
        # Actual load
        try:
            df = _retry_on_server_error(
                client.query_load,
                entsoe_zone,
                start=start,
                end=end,
            )
            rows = transform_load(df, zone, is_forecast=False)
            total += insert_total_load(con, rows)
            logger.info("load_actual: %s → %d rows", zone, len(rows))
        except NoMatchingDataError:
            logger.warning("load_actual: no data for %s", zone)
        except Exception:
            logger.error("load_actual: error for %s\n%s", zone, traceback.format_exc())
        # Load forecast
        try:
            df = _retry_on_server_error(
                client.query_load_forecast,
                entsoe_zone,
                start=start,
                end=end,
            )
            rows = transform_load(df, zone, is_forecast=True)
            total += insert_total_load(con, rows)
            logger.info("load_forecast: %s → %d rows", zone, len(rows))
        except NoMatchingDataError:
            logger.warning("load_forecast: no data for %s", zone)
        except Exception:
            logger.error(
                "load_forecast: error for %s\n%s", zone, traceback.format_exc()
            )
    return total


def ingest_cross_border_flows(
    con: duckdb.DuckDBPyConnection,
    client: EntsoePandasClient,
    borders: list[tuple[str, str]],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> int:
    """Fetch and store cross-border flows for the given borders.

    Borders are ENTSO-E zone code pairs (e.g. ``("EE", "FI")``).
    """
    total = 0
    for from_zone, to_zone in borders:
        try:
            series = _retry_on_server_error(
                client.query_crossborder_flows,
                from_zone,
                to_zone,
                start=start,
                end=end,
            )
            rows = transform_cross_border_flows(series, from_zone, to_zone)
            total += insert_cross_border_flows(con, rows)
            logger.info("cross_border: %s→%s → %d rows", from_zone, to_zone, len(rows))
        except NoMatchingDataError:
            logger.warning("cross_border: no data for %s→%s", from_zone, to_zone)
        except Exception:
            logger.error(
                "cross_border: error for %s→%s\n%s",
                from_zone,
                to_zone,
                traceback.format_exc(),
            )
    return total


def ingest_outages(
    con: duckdb.DuckDBPyConnection,
    client: EntsoePandasClient,
    zones: list[BiddingZone],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> int:
    """Fetch and store generation unavailability (outages) for the given zones."""
    total = 0
    for zone in zones:
        try:
            df = _retry_on_server_error(
                client.query_unavailability_of_generation_units,
                ZONE_TO_ENTSOE[zone],
                start=start,
                end=end,
            )
            rows = transform_outages(df, zone)
            total += insert_outages(con, rows)
            logger.info("outages: %s → %d rows", zone, len(rows))
        except NoMatchingDataError:
            logger.warning("outages: no data for %s", zone)
        except Exception:
            logger.error("outages: error for %s\n%s", zone, traceback.format_exc())
    return total


# ---------------------------------------------------------------------------
# Fetch-only functions (API call + transform, no DB write).
# Thread-safe — suitable for use with concurrent.futures.
# ---------------------------------------------------------------------------


def _rate_limit(limiter: RateLimiter | None) -> None:
    if limiter is not None:
        limiter.acquire()


def fetch_day_ahead_prices(
    client: EntsoePandasClient,
    zone: BiddingZone,
    start: pd.Timestamp,
    end: pd.Timestamp,
    limiter: RateLimiter | None = None,
) -> list:
    """Fetch and transform day-ahead prices for a single zone."""
    _rate_limit(limiter)
    series = _retry_on_server_error(
        client.query_day_ahead_prices,
        ZONE_TO_ENTSOE[zone],
        start=start,
        end=end,
    )
    rows = transform_day_ahead_prices(series, zone)
    logger.info("day_ahead_prices: %s → %d rows", zone, len(rows))
    return rows


def fetch_generation(
    client: EntsoePandasClient,
    zone: BiddingZone,
    start: pd.Timestamp,
    end: pd.Timestamp,
    limiter: RateLimiter | None = None,
) -> list:
    """Fetch and transform generation per type for a single zone."""
    _rate_limit(limiter)
    df = _retry_on_server_error(
        client.query_generation,
        ZONE_TO_ENTSOE[zone],
        start=start,
        end=end,
    )
    rows = transform_generation(df, zone)
    logger.info("generation: %s → %d rows", zone, len(rows))
    return rows


def fetch_load_actual(
    client: EntsoePandasClient,
    zone: BiddingZone,
    start: pd.Timestamp,
    end: pd.Timestamp,
    limiter: RateLimiter | None = None,
) -> list:
    """Fetch and transform actual load for a single zone."""
    _rate_limit(limiter)
    df = _retry_on_server_error(
        client.query_load,
        ZONE_TO_ENTSOE[zone],
        start=start,
        end=end,
    )
    rows = transform_load(df, zone, is_forecast=False)
    logger.info("load_actual: %s → %d rows", zone, len(rows))
    return rows


def fetch_load_forecast(
    client: EntsoePandasClient,
    zone: BiddingZone,
    start: pd.Timestamp,
    end: pd.Timestamp,
    limiter: RateLimiter | None = None,
) -> list:
    """Fetch and transform load forecast for a single zone."""
    _rate_limit(limiter)
    df = _retry_on_server_error(
        client.query_load_forecast,
        ZONE_TO_ENTSOE[zone],
        start=start,
        end=end,
    )
    rows = transform_load(df, zone, is_forecast=True)
    logger.info("load_forecast: %s → %d rows", zone, len(rows))
    return rows


def fetch_cross_border_flows(
    client: EntsoePandasClient,
    from_zone: str,
    to_zone: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    limiter: RateLimiter | None = None,
) -> list:
    """Fetch and transform cross-border flows for a single border pair."""
    _rate_limit(limiter)
    series = _retry_on_server_error(
        client.query_crossborder_flows,
        from_zone,
        to_zone,
        start=start,
        end=end,
    )
    rows = transform_cross_border_flows(series, from_zone, to_zone)
    logger.info("cross_border: %s→%s → %d rows", from_zone, to_zone, len(rows))
    return rows


def fetch_outages(
    client: EntsoePandasClient,
    zone: BiddingZone,
    start: pd.Timestamp,
    end: pd.Timestamp,
    limiter: RateLimiter | None = None,
) -> list:
    """Fetch and transform outages for a single zone."""
    _rate_limit(limiter)
    df = _retry_on_server_error(
        client.query_unavailability_of_generation_units,
        ZONE_TO_ENTSOE[zone],
        start=start,
        end=end,
    )
    rows = transform_outages(df, zone)
    logger.info("outages: %s → %d rows", zone, len(rows))
    return rows
