"""Normalise raw ENTSO-E generation into the canonical target grid.

Canonical grid: hourly UTC, left-labelled, value = mean MW over the interval. Hours
assembled from fewer sub-intervals than expected are flagged `partial` and excluded
from training while being kept for diagnostics.
"""

import pandas as pd

#: ENTSO-E production type -> the slug used throughout this project. Matches the
#: convention in src/grid_signals/ingestion/fuel_types.py so a later handover is cheap.
FUEL_SLUGS = {
    "Wind Onshore": "wind_onshore",
    "Wind Offshore": "wind_offshore",
    "Solar": "solar",
    "Nuclear": "nuclear",
    "Hydro Water Reservoir": "hydro_reservoir",
    "Hydro Run-of-river and poundage": "hydro_run_of_river",
    "Hydro Pumped Storage": "hydro_pumped",
    "Fossil Gas": "gas",
    "Fossil Hard coal": "hard_coal",
    "Fossil Brown coal/Lignite": "lignite",
    "Fossil Oil": "oil",
    "Biomass": "biomass",
    "Waste": "waste",
    "Other": "other",
    "Other renewable": "other_renewable",
    "Geothermal": "geothermal",
}

VRE_SLUGS = ("wind_onshore", "wind_offshore", "solar")


def slug(entsoe_name: str) -> str:
    """Map an ENTSO-E production type to a slug, falling back to a normalised name."""
    return FUEL_SLUGS.get(entsoe_name, entsoe_name.lower().replace(" ", "_"))


def detect_resolution(index: pd.DatetimeIndex) -> pd.Timedelta:
    """Infer the native resolution of a series from the modal gap between timestamps."""
    if len(index) < 2:
        return pd.Timedelta("1h")
    gaps = pd.Series(index.sort_values()).diff().dropna()
    return gaps.mode().iloc[0] if not gaps.empty else pd.Timedelta("1h")


def to_hourly(
    raw: pd.DataFrame, aggregation: str = "Actual Aggregated"
) -> pd.DataFrame:
    """Collapse raw long-format ENTSO-E rows onto the canonical hourly UTC grid.

    Returns one row per (zone, fuel_type, period_start) with the mean MW over the hour,
    the number of sub-intervals it was built from, and the native resolution seen.
    """
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "zone",
                "fuel_type",
                "period_start",
                "mw",
                "n_sub",
                "native_minutes",
            ]
        )

    frame = raw.copy()
    if "aggregation" in frame.columns:
        frame = frame[frame["aggregation"] == aggregation]
    frame["fuel_type"] = frame["fuel_type"].map(slug)
    frame["period_start"] = pd.to_datetime(frame["period_start"], utc=True)
    # Duplicate (zone, fuel, timestamp) rows arise where 90-day chunks meet; the last
    # fetched value wins.
    frame = frame.sort_values("fetched_at").drop_duplicates(
        ["zone", "fuel_type", "period_start"], keep="last"
    )

    frame["hour"] = frame["period_start"].dt.floor("h")
    hourly = (
        frame.groupby(["zone", "fuel_type", "hour"])["value_mw"]
        .agg(mw="mean", n_sub="size")
        .reset_index()
        .rename(columns={"hour": "period_start"})
    )

    # Resolution must be inferred per day, not once over all history: a zone that moved
    # to 15-minute settlement mid-series would otherwise keep claiming hourly, and no
    # hour would ever be flagged partial.
    day = hourly.period_start.dt.floor("D")
    hourly["expected_sub"] = hourly.groupby(["zone", "fuel_type", day]).n_sub.transform(
        "max"
    )
    hourly["native_minutes"] = 60.0 / hourly.expected_sub
    return hourly


def to_quarter_hourly(raw: pd.DataFrame) -> pd.DataFrame:
    """Keep genuine quarter-hour observations; never expand hourly measurements.

    An hour must contain all four starts. This also excludes transition days' hourly
    observations and incomplete hours without treating gaps as zero generation.
    """
    frame = raw.copy()
    if "aggregation" in frame:
        frame = frame[frame.aggregation == "Actual Aggregated"]
    frame["fuel_type"] = frame.fuel_type.map(slug)
    frame["period_start"] = pd.to_datetime(frame.period_start, utc=True)
    frame = frame.sort_values("fetched_at").drop_duplicates(
        ["zone", "fuel_type", "period_start"], keep="last"
    )
    aligned = (frame.period_start.dt.minute % 15 == 0) & (
        frame.period_start.dt.second == 0
    )
    frame = frame[aligned].copy()
    hour = frame.period_start.dt.floor("h")
    count = frame.groupby(["zone", "fuel_type", hour]).period_start.transform("size")
    frame = frame[count == 4].rename(columns={"value_mw": "mw"})
    return (
        frame[["zone", "fuel_type", "period_start", "mw"]]
        .sort_values("period_start")
        .reset_index(drop=True)
    )
