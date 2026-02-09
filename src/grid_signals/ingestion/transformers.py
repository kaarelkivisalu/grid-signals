"""Pure functions: pandas objects (entsoe-py output) → Pydantic models."""

from datetime import UTC

import pandas as pd

from grid_signals.ingestion.fuel_types import normalize_fuel_type
from grid_signals.models import (
    BiddingZone,
    CrossBorderFlow,
    DayAheadPrice,
    GenerationByType,
    Outage,
    TotalLoad,
)


def transform_day_ahead_prices(
    series: pd.Series, zone: BiddingZone
) -> list[DayAheadPrice]:
    """Convert entsoe-py day-ahead price Series to DayAheadPrice models."""
    rows: list[DayAheadPrice] = []
    for ts, price in series.items():
        if pd.isna(price):
            continue
        rows.append(
            DayAheadPrice(
                zone=zone,
                timestamp=ts.to_pydatetime().astimezone(UTC),
                price_eur_mwh=float(price),
            )
        )
    return rows


def transform_generation(
    df: pd.DataFrame, zone: BiddingZone
) -> list[GenerationByType]:
    """Convert entsoe-py generation DataFrame to GenerationByType models.

    Handles both MultiIndex columns (with "Actual Aggregated" / "Actual
    Consumption" second level) and flat string columns.  Only keeps "Actual
    Aggregated" when a second level is present.
    """
    rows: list[GenerationByType] = []
    for ts, row in df.iterrows():
        ts_utc = ts.to_pydatetime().astimezone(UTC)
        for col, value in row.items():
            if pd.isna(value):
                continue
            # MultiIndex: (fuel_type, aggregation_type)
            if isinstance(col, tuple):
                fuel_raw, agg_type = col
                if agg_type != "Actual Aggregated":
                    continue
            else:
                fuel_raw = col
            rows.append(
                GenerationByType(
                    zone=zone,
                    timestamp=ts_utc,
                    fuel_type=normalize_fuel_type(fuel_raw),
                    generation_mw=float(value),
                )
            )
    return rows


def transform_load(
    df: pd.DataFrame, zone: BiddingZone, is_forecast: bool
) -> list[TotalLoad]:
    """Convert entsoe-py load DataFrame to TotalLoad models.

    The DataFrame typically has a single column; we sum across columns
    if there happen to be multiple.
    """
    rows: list[TotalLoad] = []
    for ts, row in df.iterrows():
        total = row.sum()
        if pd.isna(total):
            continue
        rows.append(
            TotalLoad(
                zone=zone,
                timestamp=ts.to_pydatetime().astimezone(UTC),
                load_mw=float(total),
                is_forecast=is_forecast,
            )
        )
    return rows


def transform_cross_border_flows(
    series: pd.Series, from_zone: BiddingZone, to_zone: BiddingZone
) -> list[CrossBorderFlow]:
    """Convert entsoe-py cross-border flow Series to CrossBorderFlow models."""
    rows: list[CrossBorderFlow] = []
    for ts, flow in series.items():
        if pd.isna(flow):
            continue
        rows.append(
            CrossBorderFlow(
                from_zone=from_zone,
                to_zone=to_zone,
                timestamp=ts.to_pydatetime().astimezone(UTC),
                flow_mw=float(flow),
            )
        )
    return rows


def transform_outages(
    df: pd.DataFrame, zone: BiddingZone
) -> list[Outage]:
    """Convert entsoe-py unavailability DataFrame to Outage models.

    Groups by mRID, takes the latest revision, filters cancelled events,
    maps business type to planned/unplanned, and computes unavailable_mw
    as nominal_power - available_capacity.
    """
    if df.empty:
        return []

    # Keep only the latest revision per mRID
    latest_idx = df.groupby("mrid")["revision"].idxmax()
    df = df.loc[latest_idx]

    rows: list[Outage] = []
    for _, r in df.iterrows():
        # Skip cancelled outages
        status = str(r.get("status", "")).lower()
        if "cancelled" in status or "canceled" in status:
            continue

        btype = str(r.get("businesstype", "")).lower()
        outage_type = "unplanned" if "unplanned" in btype else "planned"

        nominal = float(r.get("nominal_power", 0) or 0)
        available = float(r.get("available_capacity", 0) or 0)
        unavailable = nominal - available

        end_time = r.get("end")
        if pd.isna(end_time):
            end_time = None
        else:
            end_time = pd.Timestamp(end_time).to_pydatetime().astimezone(UTC)

        start_time = pd.Timestamp(r["start"]).to_pydatetime().astimezone(UTC)

        rows.append(
            Outage(
                zone=zone,
                asset_name=str(r.get("production_resource_name", "Unknown")),
                fuel_type=normalize_fuel_type(
                    str(r.get("production_type", "Other"))
                ),
                outage_type=outage_type,
                unavailable_mw=unavailable,
                start_time=start_time,
                end_time=end_time,
                message_id=str(r["mrid"]),
            )
        )
    return rows
