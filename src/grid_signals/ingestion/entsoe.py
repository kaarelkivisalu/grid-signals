"""Orchestrator functions: fetch from ENTSO-E, transform, insert into DuckDB."""

import logging
import traceback

import duckdb
import pandas as pd
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

logger = logging.getLogger(__name__)


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
            series = client.query_day_ahead_prices(
                ZONE_TO_ENTSOE[zone], start=start, end=end
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
            df = client.query_generation(
                ZONE_TO_ENTSOE[zone], start=start, end=end
            )
            rows = transform_generation(df, zone)
            total += insert_generation_by_type(con, rows)
            logger.info("generation: %s → %d rows", zone, len(rows))
        except NoMatchingDataError:
            logger.warning("generation: no data for %s", zone)
        except Exception:
            logger.error(
                "generation: error for %s\n%s", zone, traceback.format_exc()
            )
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
            df = client.query_load(entsoe_zone, start=start, end=end)
            rows = transform_load(df, zone, is_forecast=False)
            total += insert_total_load(con, rows)
            logger.info("load_actual: %s → %d rows", zone, len(rows))
        except NoMatchingDataError:
            logger.warning("load_actual: no data for %s", zone)
        except Exception:
            logger.error(
                "load_actual: error for %s\n%s", zone, traceback.format_exc()
            )
        # Load forecast
        try:
            df = client.query_load_forecast(entsoe_zone, start=start, end=end)
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

    Borders are ENTSO-E zone code pairs (e.g. ``("EE", "FI")``)."""
    total = 0
    for from_zone, to_zone in borders:
        try:
            series = client.query_crossborder_flows(
                from_zone,
                to_zone,
                start=start,
                end=end,
            )
            rows = transform_cross_border_flows(series, from_zone, to_zone)
            total += insert_cross_border_flows(con, rows)
            logger.info(
                "cross_border: %s→%s → %d rows", from_zone, to_zone, len(rows)
            )
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
            df = client.query_unavailability_of_generation_units(
                ZONE_TO_ENTSOE[zone], start=start, end=end
            )
            rows = transform_outages(df, zone)
            total += insert_outages(con, rows)
            logger.info("outages: %s → %d rows", zone, len(rows))
        except NoMatchingDataError:
            logger.warning("outages: no data for %s", zone)
        except Exception:
            logger.error(
                "outages: error for %s\n%s", zone, traceback.format_exc()
            )
    return total
