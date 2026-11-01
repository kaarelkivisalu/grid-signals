"""Turn the turbine fleet into a small set of representative NWP query points.

One point per bidding zone -- what grid-signals ingests today -- is far too coarse for
SE3, which spans from Varmland to the Uppland coast. Clustering the actual fleet,
weighted by rated power, puts the query points where the megawatts are.
"""

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from grid_signals.forecast.sources import fleet

logger = logging.getLogger(__name__)

#: SE3 spans roughly 500 km; 8 clusters resolve the west-east and coastal structure
#: without multiplying API calls. Revisit against a lattice ablation.
DEFAULT_CLUSTERS = 8

#: Cluster in a projected CRS -- a degree of longitude is ~55 km at this latitude but a
#: degree of latitude is 111 km, so clustering in degrees distorts distances.
METRIC_CRS = 3006


def build(
    zone: str = "SE3",
    n_clusters: int = DEFAULT_CLUSTERS,
    *,
    offshore: bool = False,
    seed: int = 0,
) -> pd.DataFrame:
    """Capacity-weighted k-means over the operational fleet of one zone.

    Returns one row per cluster with its centroid in WGS84, the capacity it represents
    and its share of the zone total -- the weights used to aggregate point forecasts
    back to a zonal value.
    """
    turbines = fleet.load_turbines()
    sel = turbines[
        (turbines.zone == zone)
        & (turbines.offshore == offshore)
        & ~turbines.decommissioned
    ]
    if sel.empty:
        msg = f"no operational turbines for {zone}"
        raise ValueError(msg)

    projected = sel.to_crs(METRIC_CRS)
    coords = np.column_stack([projected.geometry.x, projected.geometry.y])
    model = KMeans(n_clusters=n_clusters, random_state=seed, n_init=10)
    labels = model.fit_predict(coords, sample_weight=sel.capacity_mw.to_numpy())

    centroids = gpd.GeoSeries(
        gpd.points_from_xy(model.cluster_centers_[:, 0], model.cluster_centers_[:, 1]),
        crs=METRIC_CRS,
    ).to_crs(4326)

    grouped = sel.assign(cluster=labels).groupby("cluster")
    out = pd.DataFrame(
        {
            "point_id": [f"{zone.lower()}_w{i:02d}" for i in range(n_clusters)],
            "cluster": range(n_clusters),
            "latitude": centroids.y.to_numpy().round(4),
            "longitude": centroids.x.to_numpy().round(4),
            "capacity_mw": grouped.capacity_mw.sum()
            .reindex(range(n_clusters))
            .to_numpy(),
            "n_turbines": grouped.size().reindex(range(n_clusters)).to_numpy(),
            "mean_hub_height_m": grouped.hub_height_m.mean()
            .reindex(range(n_clusters))
            .to_numpy()
            .round(1),
        }
    )
    out["weight"] = out.capacity_mw / out.capacity_mw.sum()
    logger.info(
        "%s: %s clusters covering %.0f MW", zone, n_clusters, out.capacity_mw.sum()
    )
    return out.sort_values("point_id").reset_index(drop=True)
