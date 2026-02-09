"""ENTSO-E data ingestion layer."""

from grid_signals.ingestion.client import get_entsoe_client
from grid_signals.ingestion.entsoe import (
    ingest_cross_border_flows,
    ingest_day_ahead_prices,
    ingest_generation_per_type,
    ingest_outages,
    ingest_total_load,
)

__all__ = [
    "get_entsoe_client",
    "ingest_cross_border_flows",
    "ingest_day_ahead_prices",
    "ingest_generation_per_type",
    "ingest_outages",
    "ingest_total_load",
]
