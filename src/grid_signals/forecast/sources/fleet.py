"""Vindbrukskollen: the Swedish turbine registry, and the SE3 capacity series.

Vindbrukskollen is maintained by the Swedish Energy Agency and the county administrative
boards, updated daily, and carries exactly what capacity normalisation needs: per-turbine
coordinates, rated power, commissioning date, hub height and turbine model.

It is authoritative on *timing* (when capacity arrived). ENTSO-E A68 is authoritative on
*level*, but is published per country for Sweden rather than per bidding zone, so the SE3
split comes from here and A68 only provides a national cross-check.
"""

import logging
from datetime import date

import geopandas as gpd
import pandas as pd

from grid_signals.forecast import paths

logger = logging.getLogger(__name__)

GPKG = paths.RAW / "vindbrukskollen" / "lst.vbk_vindkraftverk.gpkg"
ZONES_GEOJSON = paths.CONFIGS / "se_bidding_zones.geojson"

DOWNLOAD_URL = (
    "https://ext-dokument.lansstyrelsen.se/gemensamt/geodata/ShapeExport/"
    "lst.vbk_vindkraftverk.zip"
)

#: Only these turbines physically exist and generate.
STATUS_OPERATIONAL = "Uppfört"
STATUS_DECOMMISSIONED = "Nedmonterat"

#: `PLACERING` values arrive with trailing whitespace in the source data.
OFFSHORE_PLACEMENT = "Vatten"

#: SWEREF99 TM -- the registry's native projected CRS, used for distance work.
METRIC_CRS = 3006


def load_turbines() -> gpd.GeoDataFrame:
    """Read the registry, keep built turbines, and assign each to a bidding zone.

    Returns one row per turbine in EPSG:4326 with tidy column names. Turbines that are
    merely permitted or under consideration are dropped -- counting them would inflate
    capacity and depress every capacity factor.
    """
    if not GPKG.exists():
        msg = f"{GPKG} is missing; download it from {DOWNLOAD_URL}"
        raise FileNotFoundError(msg)

    raw = gpd.read_file(GPKG)
    built = raw[raw.STATUS.isin({STATUS_OPERATIONAL, STATUS_DECOMMISSIONED})].copy()

    # Multipoint geometries hold a single point each; take the representative point so
    # the centroid warning for geographic CRS never arises.
    built["geometry"] = built.geometry.representative_point()
    built = built.to_crs(4326)

    turbines = gpd.GeoDataFrame(
        {
            "turbine_id": built.VERKID,
            "site_id": built.OMRID,
            "capacity_mw": pd.to_numeric(built.MAXEFFEKT, errors="coerce"),
            "commissioned": pd.to_datetime(built.UPPFORT, errors="coerce").dt.date,
            "decommissioned": built.STATUS.eq(STATUS_DECOMMISSIONED),
            "hub_height_m": pd.to_numeric(built.NAVHOJD, errors="coerce"),
            "rotor_diameter_m": pd.to_numeric(built.ROTDIAMETER, errors="coerce"),
            "manufacturer": built.FABRIKAT.astype("string").str.strip(),
            "model": built.MODELL.astype("string").str.strip(),
            "offshore": built.PLACERING.astype("string")
            .str.strip()
            .eq(OFFSHORE_PLACEMENT)
            .fillna(value=False)
            .astype(bool),
            "county": built.LANSNAMN.astype("string").str.strip(),
            "last_updated": pd.to_datetime(built.SenasteUppdatering, errors="coerce"),
        },
        geometry=built.geometry,
        crs=4326,
    )
    turbines = turbines.dropna(subset=["capacity_mw", "commissioned"])
    return assign_zone(turbines)


def assign_zone(turbines: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Spatial-join each turbine onto a bidding-zone polygon.

    The polygons are committed in `configs/se_bidding_zones.geojson` because the zone
    boundary is a modelling assumption, not data.
    """
    zones = gpd.read_file(ZONES_GEOJSON).to_crs(4326)
    joined = gpd.sjoin(
        turbines, zones[["zone", "geometry"]], how="left", predicate="within"
    )
    joined = joined.drop(columns=["index_right"])

    unmatched = joined.zone.isna()
    if unmatched.any():
        # Coastal turbines can fall just outside the polygon; snap to the nearest zone.
        nearest = gpd.sjoin_nearest(
            turbines[unmatched.to_numpy()].to_crs(METRIC_CRS),
            zones[["zone", "geometry"]].to_crs(METRIC_CRS),
            how="left",
        )
        joined.loc[unmatched, "zone"] = nearest.zone.to_numpy()[: int(unmatched.sum())]
        logger.info("snapped %s turbines to the nearest zone", int(unmatched.sum()))
    return joined


def capacity_series(
    turbines: gpd.GeoDataFrame, zone: str, *, offshore: bool = False
) -> pd.DataFrame:
    """Daily installed capacity for one zone, from commissioning dates.

    Decommissioned turbines are removed from the date they were last updated, which is
    the best proxy the registry offers -- it carries no explicit decommissioning date.
    """
    sel = turbines[(turbines.zone == zone) & (turbines.offshore == offshore)]
    if sel.empty:
        return pd.DataFrame(columns=["date", "capacity_mw"])

    events = [
        pd.DataFrame(
            {"date": pd.to_datetime(sel.commissioned), "delta": sel.capacity_mw}
        )
    ]
    gone = sel[sel.decommissioned]
    if not gone.empty:
        events.append(
            pd.DataFrame(
                {"date": gone.last_updated.dt.normalize(), "delta": -gone.capacity_mw}
            )
        )

    deltas = pd.concat(events).dropna(subset=["date"]).groupby("date")["delta"].sum()
    daily = deltas.sort_index().cumsum()
    index = pd.date_range(daily.index.min(), pd.Timestamp.today().normalize(), freq="D")
    return (
        daily.reindex(index)
        .ffill()
        .rename("capacity_mw")
        .rename_axis("date")
        .reset_index()
    )


def capacity_at(series: pd.DataFrame, when: date) -> float:
    """Installed capacity on a given date, carrying the last known value forward."""
    prior = series[series.date <= pd.Timestamp(when)]
    return float(prior.capacity_mw.iloc[-1]) if not prior.empty else 0.0
