"""Pure functions: pandas objects (entsoe-py output) → Pydantic models."""

from datetime import UTC, timedelta

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


def _detect_interval(index: pd.DatetimeIndex) -> timedelta:
    """Infer the period duration from a DatetimeIndex."""
    if len(index) >= 2:
        return (index[1] - index[0]).to_pytimedelta()
    return timedelta(hours=1)  # safe fallback


def transform_day_ahead_prices(
    series: pd.Series, zone: BiddingZone
) -> list[DayAheadPrice]:
    """Convert entsoe-py day-ahead price Series to DayAheadPrice models."""
    interval = _detect_interval(series.index)
    rows: list[DayAheadPrice] = []
    for ts, price in series.items():
        if pd.isna(price):
            continue
        period_start = ts.to_pydatetime().astimezone(UTC)
        rows.append(
            DayAheadPrice(
                zone=zone,
                period_start=period_start,
                period_end=period_start + interval,
                price_eur_mwh=float(price),
            )
        )
    return rows


def transform_generation(df: pd.DataFrame, zone: BiddingZone) -> list[GenerationByType]:
    """Convert entsoe-py generation DataFrame to GenerationByType models.

    Handles both MultiIndex columns (with "Actual Aggregated" / "Actual
    Consumption" second level) and flat string columns.  Only keeps "Actual
    Aggregated" when a second level is present.
    """
    interval = _detect_interval(df.index)
    rows: list[GenerationByType] = []
    for ts, row in df.iterrows():
        period_start = ts.to_pydatetime().astimezone(UTC)
        for col, value in row.items():
            if pd.isna(value):
                continue
            # MultiIndex: (fuel_type, aggregation_type)  # noqa: ERA001
            if isinstance(col, tuple):
                fuel_raw, agg_type = col
                if agg_type != "Actual Aggregated":
                    continue
            else:
                fuel_raw = col
            rows.append(
                GenerationByType(
                    zone=zone,
                    period_start=period_start,
                    period_end=period_start + interval,
                    fuel_type=normalize_fuel_type(fuel_raw),
                    generation_mw=float(value),
                )
            )
    return rows


def transform_load(
    df: pd.DataFrame, zone: BiddingZone, *, is_forecast: bool
) -> list[TotalLoad]:
    """Convert entsoe-py load DataFrame to TotalLoad models.

    The DataFrame typically has a single column; we sum across columns
    if there happen to be multiple.
    """
    interval = _detect_interval(df.index)
    rows: list[TotalLoad] = []
    for ts, row in df.iterrows():
        total = row.sum()
        if pd.isna(total):
            continue
        period_start = ts.to_pydatetime().astimezone(UTC)
        rows.append(
            TotalLoad(
                zone=zone,
                period_start=period_start,
                period_end=period_start + interval,
                load_mw=float(total),
                is_forecast=is_forecast,
            )
        )
    return rows


def transform_cross_border_flows(
    series: pd.Series, from_zone: str, to_zone: str
) -> list[CrossBorderFlow]:
    """Convert entsoe-py cross-border flow Series to CrossBorderFlow models."""
    interval = _detect_interval(series.index)
    rows: list[CrossBorderFlow] = []
    for ts, flow in series.items():
        if pd.isna(flow):
            continue
        period_start = ts.to_pydatetime().astimezone(UTC)
        rows.append(
            CrossBorderFlow(
                from_zone=from_zone,
                to_zone=to_zone,
                period_start=period_start,
                period_end=period_start + interval,
                flow_mw=float(flow),
            )
        )
    return rows


def transform_outages(df: pd.DataFrame, zone: BiddingZone) -> list[Outage]:
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

        raw_nominal = r.get("nominal_power", 0)
        raw_available = r.get("available_capacity", 0)
        nominal = 0.0 if pd.isna(raw_nominal) else float(raw_nominal)
        available = 0.0 if pd.isna(raw_available) else float(raw_available)
        unavailable = nominal - available

        period_end = r.get("end")
        if pd.isna(period_end):
            period_end = None
        else:
            period_end = pd.Timestamp(period_end).to_pydatetime().astimezone(UTC)

        period_start = pd.Timestamp(r["start"]).to_pydatetime().astimezone(UTC)

        rows.append(
            Outage(
                zone=zone,
                asset_name=str(r.get("production_resource_name", "Unknown")),
                fuel_type=normalize_fuel_type(str(r.get("production_type", "Other"))),
                outage_type=outage_type,
                unavailable_mw=unavailable,
                period_start=period_start,
                period_end=period_end,
                message_id=str(r["mrid"]),
            )
        )
    return rows
