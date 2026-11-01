"""Hourly zonal features from ERA5, built turbine by turbine.

This is the most physically detailed weather-to-power chain the project has, and it is
deliberately richer than the forecast path: the point is to find the *ceiling* on how
much of SE3 generation weather explains, so every simplification that could be blamed
for a miss is removed.

* Each turbine reads its own ERA5 cell rather than one of eight cluster centroids.
* Wind is carried to each turbine's own hub height with the shear exponent measured
  between 10 m and 100 m, hour by hour, instead of a fixed profile.
* Each turbine gets a power curve derived from its **specific power** (rated W per m2
  of rotor). A 250 W/m2 low-wind machine reaches rated around 9 m/s; a 450 W/m2 one
  not until ~12 m/s. The generic class II curve treats them identically.
* The fleet is live: a turbine contributes only from its commissioning date, so the
  modelled output carries the build-out without any capacity denominator at all.

ERA5 fields are instantaneous at the top of the hour; ENTSO-E values are means over the
hour that *starts* at `period_start`. Features are therefore averaged over the two
bounding instants before they are aligned to the target.
"""

import logging

import numpy as np
import pandas as pd
import xarray as xr

from grid_signals.forecast.features import wind

logger = logging.getLogger(__name__)

#: Effective aerodynamic efficiency below rated, including drivetrain losses. Chosen so
#: that a ~300 W/m2 turbine reaches rated near 10.5 m/s, typical of the SE3 fleet.
CP_EFFECTIVE = 0.42
CUT_IN_MS = 3.0
CUT_OUT_MS = 25.0

#: Specific power outside this range is a registry error (a kW/MW or radius/diameter
#: mix-up), not a real turbine.
SPECIFIC_POWER_BOUNDS = (150.0, 700.0)

#: Sub-grid wind variability. A 31 km cell is not one wind speed, so each turbine sees a
#: spread around the cell value; smoothing the curve with it is the standard correction
#: for reanalysis-driven wind models (cf. Renewables.ninja, Staffell & Pfenninger 2016).
SMOOTHING_SIGMA_MS = 1.0
SMOOTHING_SIGMA_REL = 0.10
_NODES, _WEIGHTS = np.polynomial.hermite_e.hermegauss(9)
_WEIGHTS /= _WEIGHTS.sum()


def turbine_table(turbines: pd.DataFrame, zone: str = "SE3") -> pd.DataFrame:
    """Onshore turbines of one zone, with the attributes the physics needs filled in."""
    sel = turbines[(turbines.zone == zone) & ~turbines.offshore].copy()
    sel["latitude"] = sel.geometry.y
    sel["longitude"] = sel.geometry.x

    area = np.pi * (sel.rotor_diameter_m / 2) ** 2
    specific = sel.capacity_mw * 1e6 / area
    valid = specific.between(*SPECIFIC_POWER_BOUNDS)
    sel["specific_power"] = specific.where(valid)
    # Missing attributes are filled by capacity band, since small old machines are low
    # and short while modern ones are tall; a zone-wide median would mix the two.
    band = pd.cut(sel.capacity_mw, [0, 1, 2.5, 4, 100])
    for column in ("specific_power", "hub_height_m"):
        sel[column] = sel[column].fillna(
            sel.groupby(band, observed=True)[column].transform("median")
        )
        sel[column] = sel[column].fillna(sel[column].median())

    sel["commissioned"] = pd.to_datetime(sel.commissioned, utc=True)
    # The registry has no decommissioning date; its last update is the proxy, exactly
    # as in `fleet.capacity_series`, so the two fleets agree.
    sel["retired"] = pd.to_datetime(
        sel.last_updated.where(sel.decommissioned), utc=True
    )
    return sel.reset_index(drop=True)


def specific_power_curve(speed: np.ndarray, specific_power: np.ndarray) -> np.ndarray:
    """Normalised output of a turbine with the given specific power, at air density 1.225."""
    raw = 0.5 * wind.RHO_REFERENCE * CP_EFFECTIVE * speed**3 / specific_power
    out = np.clip(raw, 0.0, 1.0)
    return np.where((speed < CUT_IN_MS) | (speed >= CUT_OUT_MS), 0.0, out)


def smoothed_curve(speed: np.ndarray, specific_power: np.ndarray) -> np.ndarray:
    """The specific-power curve averaged over sub-grid speed variability."""
    sigma = SMOOTHING_SIGMA_MS + SMOOTHING_SIGMA_REL * speed
    total = np.zeros_like(speed)
    for node, weight in zip(_NODES, _WEIGHTS, strict=True):
        total += weight * specific_power_curve(
            np.maximum(speed + node * sigma, 0.0), specific_power
        )
    return total


def nearest_cells(grid: xr.Dataset, turbines: pd.DataFrame) -> pd.DataFrame:
    """Index along `cell` of the ERA5 cell nearest each turbine."""
    lats = grid.latitude.to_numpy()
    lons = grid.longitude.to_numpy()
    distance = (turbines.latitude.to_numpy()[:, None] - lats[None, :]) ** 2 + (
        # A degree of longitude is about half a degree of latitude at 60 N.
        (turbines.longitude.to_numpy()[:, None] - lons[None, :]) * 0.5
    ) ** 2
    out = turbines.copy()
    out["cell"] = distance.argmin(axis=1)
    return out


def cell_series(grid: xr.Dataset, cells: np.ndarray) -> dict[str, np.ndarray]:
    """Surface fields at the given cells, as (time, cell) arrays."""
    sub = grid.isel(cell=cells).transpose("valid_time", "cell")
    speed_100 = np.hypot(sub.u100, sub.v100).to_numpy()
    speed_10 = np.hypot(sub.u10, sub.v10).to_numpy()
    temperature = sub.t2m.to_numpy()
    return {
        "speed_100": speed_100,
        "speed_10": speed_10,
        "u100": sub.u100.to_numpy(),
        "v100": sub.v100.to_numpy(),
        "alpha": wind.shear_exponent(speed_10, speed_100, 10.0, 100.0),
        "temperature": temperature - 273.15,
        "humidity": _relative_humidity(temperature, sub.d2m.to_numpy()),
        "pressure": sub.sp.to_numpy() / 100.0,
        "boundary_layer_height": sub.blh.to_numpy(),
    }


def _relative_humidity(temperature_k: np.ndarray, dewpoint_k: np.ndarray) -> np.ndarray:
    def saturation(t_c):
        return np.exp(17.625 * t_c / (t_c + 243.04))

    return np.clip(
        100.0 * saturation(dewpoint_k - 273.15) / saturation(temperature_k - 273.15),
        0,
        100,
    )


def build(
    grid: xr.Dataset, turbines: pd.DataFrame, clusters: pd.DataFrame
) -> pd.DataFrame:
    """One row per ERA5 instant: live-fleet physics and capacity-weighted weather.

    `clusters` supplies the eight centroids; each turbine joins its nearest one so that
    per-cluster features carry the same geography as the forecast path.
    """
    fleet = nearest_cells(grid, turbines)
    centroid = clusters[["latitude", "longitude"]].to_numpy()
    distance = (fleet.latitude.to_numpy()[:, None] - centroid[None, :, 0]) ** 2 + (
        (fleet.longitude.to_numpy()[:, None] - centroid[None, :, 1]) * 0.5
    ) ** 2
    fleet["cluster"] = distance.argmin(axis=1)

    cells = np.sort(fleet.cell.unique())
    fleet["cell"] = np.searchsorted(cells, fleet.cell)
    logger.info("%s turbines on %s ERA5 cells", len(fleet), len(cells))

    series = cell_series(grid, cells)
    times = pd.DatetimeIndex(pd.to_datetime(grid.valid_time.to_numpy(), utc=True))
    n_time = len(times)
    n_cluster = len(clusters)

    live_cap = np.zeros(n_time)
    mw_generic = np.zeros(n_time)
    mw_specific = np.zeros(n_time)
    mw_smooth = np.zeros(n_time)
    cluster_cap = np.zeros((n_time, n_cluster))
    cluster_mw = np.zeros((n_time, n_cluster))
    cluster_speed = np.zeros((n_time, n_cluster))
    weather = {
        k: np.zeros(n_time)
        for k in (
            "temperature",
            "humidity",
            "alpha",
            "u100",
            "v100",
            "speed_100",
            "density",
            "icing",
            "boundary_layer_height",
        )
    }
    time_ns = times.asi8

    for cell, group in fleet.groupby("cell"):
        start = pd.DatetimeIndex(group.commissioned).as_unit("ns").asi8
        retired = pd.DatetimeIndex(group.retired)
        stop = np.where(
            retired.isna(), np.iinfo(np.int64).max, retired.as_unit("ns").asi8
        )
        live = (time_ns[:, None] >= start[None, :]) & (time_ns[:, None] < stop[None, :])
        capacity = live * group.capacity_mw.to_numpy()[None, :]

        alpha = series["alpha"][:, cell][:, None]
        hub = group.hub_height_m.to_numpy()[None, :]
        speed_hub = series["speed_100"][:, cell][:, None] * (hub / 100.0) ** alpha
        density = wind.air_density(
            series["temperature"][:, cell],
            series["pressure"][:, cell],
            series["humidity"][:, cell],
        )
        corrected = wind.density_corrected_speed(speed_hub, density[:, None])
        specific = group.specific_power.to_numpy()[None, :]

        mw_generic += (capacity * wind.power_curve(corrected)).sum(axis=1)
        mw_specific += (capacity * specific_power_curve(corrected, specific)).sum(
            axis=1
        )
        smooth = capacity * smoothed_curve(
            corrected, np.broadcast_to(specific, corrected.shape)
        )
        mw_smooth += smooth.sum(axis=1)

        cap_total = capacity.sum(axis=1)
        live_cap += cap_total
        for name in (
            "temperature",
            "humidity",
            "alpha",
            "u100",
            "v100",
            "speed_100",
            "boundary_layer_height",
        ):
            weather[name] += cap_total * series[name][:, cell]
        weather["density"] += cap_total * density
        icing = (series["temperature"][:, cell] < wind.ICING_TEMP_C) & (
            series["humidity"][:, cell] > wind.ICING_HUMIDITY_PCT
        )
        weather["icing"] += cap_total * icing

        for cluster, sub in group.groupby("cluster"):
            columns = group.index.get_indexer(sub.index)
            cap = capacity[:, columns]
            cluster_cap[:, cluster] += cap.sum(axis=1)
            cluster_mw[:, cluster] += smooth[:, columns].sum(axis=1)
            cluster_speed[:, cluster] += (cap * speed_hub[:, columns]).sum(axis=1)

    safe = np.where(live_cap > 0, live_cap, np.nan)
    out = pd.DataFrame(
        {
            "valid_time": times,
            "live_capacity_mw": live_cap,
            "phys_generic_mw": mw_generic,
            "phys_specific_mw": mw_specific,
            "phys_smooth_mw": mw_smooth,
        }
    )
    for name, total in weather.items():
        out[name] = total / safe
    out["direction_sin"] = -out.u100 / np.hypot(out.u100, out.v100)
    out["direction_cos"] = -out.v100 / np.hypot(out.u100, out.v100)

    cluster_safe = np.where(cluster_cap > 0, cluster_cap, np.nan)
    for k in range(n_cluster):
        out[f"c{k}_cf"] = cluster_mw[:, k] / cluster_safe[:, k]
        out[f"c{k}_speed_hub"] = cluster_speed[:, k] / cluster_safe[:, k]
    speeds = out[[f"c{k}_speed_hub" for k in range(n_cluster)]]
    out["speed_hub_spatial_std"] = speeds.std(axis=1)
    return out


def to_hourly_intervals(instants: pd.DataFrame) -> pd.DataFrame:
    """Average consecutive instants so row `t` describes the interval [t, t+1h)."""
    frame = instants.set_index("valid_time").sort_index()
    frame = frame.asfreq("h")
    averaged = (frame + frame.shift(-1)) / 2
    # Capacity is a step function; averaging it across a commissioning instant is
    # meaningless, so it keeps the value at the interval start.
    averaged["live_capacity_mw"] = frame.live_capacity_mw
    return averaged.dropna(how="all").rename_axis("period_start").reset_index()
