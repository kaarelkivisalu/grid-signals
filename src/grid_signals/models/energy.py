from datetime import datetime

from pydantic import BaseModel

from grid_signals.models.zones import BiddingZone


class DayAheadPrice(BaseModel):
    """Hourly day-ahead electricity price for a bidding zone."""

    zone: BiddingZone
    timestamp: datetime  # UTC, start of the hour
    price_eur_mwh: float


class GenerationByType(BaseModel):
    """Hourly aggregated generation for a single fuel type in a zone."""

    zone: BiddingZone
    timestamp: datetime  # UTC
    fuel_type: str  # e.g. "wind_onshore", "solar", "nuclear", "gas", "oil_shale", "hydro"
    generation_mw: float


class TotalLoad(BaseModel):
    """Hourly total load (actual or forecast) for a zone."""

    zone: BiddingZone
    timestamp: datetime  # UTC
    load_mw: float
    is_forecast: bool


class CrossBorderFlow(BaseModel):
    """Hourly scheduled or actual cross-border flow between two zones."""

    from_zone: BiddingZone
    to_zone: BiddingZone
    timestamp: datetime  # UTC
    flow_mw: float  # positive = from → to


class Outage(BaseModel):
    """REMIT urgent market message — planned or unplanned outage."""

    zone: BiddingZone
    asset_name: str
    fuel_type: str
    outage_type: str  # "planned" or "unplanned"
    unavailable_mw: float
    start_time: datetime  # UTC
    end_time: datetime | None  # UTC, None if open-ended
    message_id: str  # REMIT message ID for deduplication
