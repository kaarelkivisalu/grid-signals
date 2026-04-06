from datetime import datetime

from pydantic import BaseModel

from grid_signals.models.zones import BiddingZone


class DayAheadPrice(BaseModel):
    """Hourly day-ahead electricity price for a bidding zone."""

    zone: BiddingZone
    period_start: datetime  # UTC, inclusive
    period_end: datetime  # UTC, exclusive
    price_eur_mwh: float


class GenerationByType(BaseModel):
    """Generation for a single fuel type in a zone (hourly or 15-min)."""

    zone: BiddingZone
    period_start: datetime  # UTC, inclusive
    period_end: datetime  # UTC, exclusive
    fuel_type: (
        str  # e.g. "wind_onshore", "solar", "nuclear", "gas", "oil_shale", "hydro"
    )
    generation_mw: float


class TotalLoad(BaseModel):
    """Total load (actual or forecast) for a zone (hourly or 15-min)."""

    zone: BiddingZone
    period_start: datetime  # UTC, inclusive
    period_end: datetime  # UTC, exclusive
    load_mw: float
    is_forecast: bool


class CrossBorderFlow(BaseModel):
    """Scheduled or actual cross-border flow between two zones (hourly or 15-min)."""

    from_zone: str  # BiddingZone code or external ENTSO-E code (e.g. "DE_LU")
    to_zone: str
    period_start: datetime  # UTC, inclusive
    period_end: datetime  # UTC, exclusive
    flow_mw: float  # positive = from → to


class Outage(BaseModel):
    """REMIT urgent market message — planned or unplanned outage."""

    zone: BiddingZone
    asset_name: str
    fuel_type: str
    outage_type: str  # "planned" or "unplanned"
    unavailable_mw: float
    period_start: datetime  # UTC
    period_end: datetime | None  # UTC, None if open-ended
    message_id: str  # REMIT message ID for deduplication
