"""Wind features: physics first, statistics second.

The power-curve transform is the highest-value feature here, and the order of operations
matters: transform **per cluster, then capacity-weight**, never the other way round.

By Jensen's inequality the two orders differ wherever the curve bends, and in opposite
directions either side of rated speed -- below rated it is convex, so transforming the
spatial mean understates output; approaching and beyond rated it saturates, so
transforming the mean overstates it. The saturating case is the one that bites: it
manufactures zonal peaks the fleet cannot physically reach, because in reality only some
clusters are at rated while others are not.
"""

import numpy as np
import pandas as pd

#: Generic IEC class II power curve, normalised to rated output. Speeds in m/s at hub
#: height. Good enough for a fleet composite; per-turbine curves are a roadmap item.
POWER_CURVE_SPEEDS = np.array(
    [0.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 25.0, 25.1, 40.0]
)
POWER_CURVE_OUTPUT = np.array(
    [0.0, 0.0, 0.03, 0.10, 0.19, 0.31, 0.47, 0.64, 0.81, 0.94, 1.0, 1.0, 0.0, 0.0]
)

#: Standard air density the power curve is defined at.
RHO_REFERENCE = 1.225
R_DRY = 287.058
R_VAPOUR = 461.495

#: Icing accretes and persists, so the instantaneous flag alone is too weak; rolling
#: counts over these windows carry the memory.
ICING_WINDOWS_H = (6, 12, 24)
ICING_TEMP_C = 1.0
ICING_HUMIDITY_PCT = 95.0

#: Wind shear exponent used to translate 10 m wind to hub height when needed.
SHEAR_EXPONENT = 1 / 7


def power_curve(speed: np.ndarray) -> np.ndarray:
    """Map hub-height wind speed to normalised power output."""
    return np.interp(speed, POWER_CURVE_SPEEDS, POWER_CURVE_OUTPUT, left=0.0, right=0.0)


def air_density(
    temperature_c: np.ndarray, pressure_hpa: np.ndarray, humidity_pct: np.ndarray
) -> np.ndarray:
    """Moist air density from temperature, surface pressure and relative humidity."""
    temperature_k = temperature_c + 273.15
    # Magnus formula for saturation vapour pressure, in Pa.
    saturation = 610.94 * np.exp(17.625 * temperature_c / (temperature_c + 243.04))
    vapour = np.clip(humidity_pct, 0, 100) / 100.0 * saturation
    dry = pressure_hpa * 100.0 - vapour
    return dry / (R_DRY * temperature_k) + vapour / (R_VAPOUR * temperature_k)


def density_corrected_speed(speed: np.ndarray, density: np.ndarray) -> np.ndarray:
    """Adjust wind speed so the reference power curve sees the right energy flux."""
    return speed * (density / RHO_REFERENCE) ** (1 / 3)


def extrapolate(speed_10m: np.ndarray, hub_height_m: float) -> np.ndarray:
    """Power-law extrapolation of 10 m wind to hub height."""
    return speed_10m * (hub_height_m / 10.0) ** SHEAR_EXPONENT


def per_point(frame: pd.DataFrame, offset: int = 1) -> pd.DataFrame:
    """Derive point-level physical features at one information-age offset.

    The error-growth feature compares this offset against the next *staler* one, never
    a fresher one -- a fresher offset would be information the forecast did not have.
    """
    suffix = f"_previous_day{offset}"
    out = frame[["valid_time", "point_id", "model"]].copy()

    speed = frame[f"wind_speed_100m{suffix}"].to_numpy()
    speed_10m = frame[f"wind_speed_10m{suffix}"].to_numpy()
    temperature = frame[f"temperature_2m{suffix}"].to_numpy()
    pressure = frame[f"surface_pressure{suffix}"].to_numpy()
    humidity = frame[f"relative_humidity_2m{suffix}"].to_numpy()
    direction = frame[f"wind_direction_100m{suffix}"].to_numpy()
    gusts = frame[f"wind_gusts_10m{suffix}"].to_numpy()

    density = air_density(temperature, pressure, humidity)
    corrected = density_corrected_speed(speed, density)

    out["wind_speed_100m"] = speed
    out["power_curve"] = power_curve(corrected)
    out["air_density"] = density
    out["speed_cubed"] = corrected**3
    # Shear and gust ratios describe boundary-layer state, which modulates how well a
    # single-height wind speed represents the rotor-swept layer.
    out["shear_ratio"] = np.divide(
        speed, speed_10m, out=np.ones_like(speed), where=speed_10m > 0.1
    )
    out["gust_factor"] = np.divide(
        gusts, speed_10m, out=np.ones_like(gusts), where=speed_10m > 0.1
    )
    out["direction_sin"] = np.sin(np.deg2rad(direction))
    out["direction_cos"] = np.cos(np.deg2rad(direction))
    out["temperature_2m"] = temperature
    out["snow_depth"] = frame[f"snow_depth{suffix}"].to_numpy()

    icing = (temperature < ICING_TEMP_C) & (humidity > ICING_HUMIDITY_PCT)
    out["icing_now"] = icing.astype(float)

    staler = f"wind_speed_100m_previous_day{offset + 1}"
    if staler in frame.columns:
        out["lead_spread"] = np.abs(speed - frame[staler].to_numpy())
    return out


#: MEPS carries wind on two height levels, which is enough to *measure* the shear
#: exponent per cluster-hour instead of assuming the 1/7 rule. Stable nocturnal
#: boundary layers reach 0.5 and above; unstable ones go slightly negative. Values
#: outside this range are numerical noise from near-calm layers, not weather.
SHEAR_BOUNDS = (-0.2, 0.8)

#: MEPS reports relative humidity as a 0-1 fraction; the icing and density helpers here
#: take percent, as Open-Meteo supplies it.
RH_FRACTION_TO_PCT = 100.0

#: No surface pressure on the height-level product, and fetching the surface product
#: would double the request count for a second-order correction. Density is driven by
#: temperature (~10% seasonal swing) far more than by pressure (~3%), so the reference
#: pressure is held fixed and the temperature and humidity terms do the work.
REFERENCE_PRESSURE_HPA = 1013.25


def shear_exponent(
    lower_speed: np.ndarray,
    upper_speed: np.ndarray,
    lower_height: float,
    upper_height: float,
) -> np.ndarray:
    """Power-law exponent implied by wind speeds at two heights."""
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = np.log(upper_speed / lower_speed) / np.log(upper_height / lower_height)
    alpha = np.where(np.isfinite(alpha), alpha, SHEAR_EXPONENT)
    # Near-calm layers produce wild ratios; clip rather than let them drive the
    # extrapolation to hub height.
    return np.clip(alpha, *SHEAR_BOUNDS)


def _components(
    speed: np.ndarray, direction_deg: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Meteorological direction back to eastward/northward components."""
    radians = np.deg2rad(direction_deg)
    return -speed * np.sin(radians), -speed * np.cos(radians)


def per_point_meps(frame: pd.DataFrame, points: pd.DataFrame) -> pd.DataFrame:
    """Point-level physical features from one MEPS run.

    Two things here are better than the Open-Meteo path rather than merely equivalent.
    The wind is interpolated to each cluster's **actual mean hub height** using the
    shear exponent measured between 80 m and 120 m, instead of taking a fixed 100 m
    level and assuming a 1/7 profile. And because a single run supplies the whole
    delivery day, none of these columns changes its information age halfway through.
    """
    lower, upper = meps_heights(frame)
    wide = frame.pivot(
        index=["run_time", "valid_time", "point_id"],
        columns="height_m",
        values=["wind_speed", "wind_direction", "temperature_c", "relative_humidity"],
    )

    speed_lower = wide["wind_speed", lower].to_numpy()
    speed_upper = wide["wind_speed", upper].to_numpy()
    alpha = shear_exponent(speed_lower, speed_upper, lower, upper)

    out = wide.index.to_frame(index=False)
    hub = out.point_id.map(points.set_index("point_id").mean_hub_height_m).to_numpy()

    speed_hub = speed_lower * (hub / lower) ** alpha
    # Direction is interpolated through the components so that veer between the levels
    # is handled as a vector, not as an angle that can wrap through 360.
    fraction = np.clip((hub - lower) / (upper - lower), 0.0, 1.0)
    u_lower, v_lower = _components(
        speed_lower, wide["wind_direction", lower].to_numpy()
    )
    u_upper, v_upper = _components(
        speed_upper, wide["wind_direction", upper].to_numpy()
    )
    u_hub = u_lower + (u_upper - u_lower) * fraction
    v_hub = v_lower + (v_upper - v_lower) * fraction

    temperature = _interpolate(wide, "temperature_c", lower, upper, fraction)
    humidity = (
        _interpolate(wide, "relative_humidity", lower, upper, fraction)
        * RH_FRACTION_TO_PCT
    )

    density = air_density(
        temperature, np.full_like(temperature, REFERENCE_PRESSURE_HPA), humidity
    )
    corrected = density_corrected_speed(speed_hub, density)

    out["wind_speed_hub"] = speed_hub
    out["power_curve"] = power_curve(corrected)
    out["air_density"] = density
    out["speed_cubed"] = corrected**3
    out["shear_exponent"] = alpha
    out["direction_sin"] = np.divide(
        -u_hub, speed_hub, out=np.zeros_like(u_hub), where=speed_hub > 0.1
    )
    out["direction_cos"] = np.divide(
        -v_hub, speed_hub, out=np.zeros_like(v_hub), where=speed_hub > 0.1
    )
    out["temperature_hub"] = temperature
    out["icing_now"] = (
        (temperature < ICING_TEMP_C) & (humidity > ICING_HUMIDITY_PCT)
    ).astype(float)
    return out


def meps_heights(frame: pd.DataFrame) -> tuple[float, float]:
    """The two height levels present, lowest first."""
    heights = sorted(frame.height_m.unique())
    if len(heights) != 2:
        msg = f"expected two MEPS height levels, found {heights}"
        raise ValueError(msg)
    return float(heights[0]), float(heights[1])


def _interpolate(
    wide: pd.DataFrame, name: str, lower: float, upper: float, fraction: np.ndarray
) -> np.ndarray:
    low = wide[name, lower].to_numpy()
    high = wide[name, upper].to_numpy()
    return low + (high - low) * fraction


def add_icing_memory(
    frame: pd.DataFrame, keys: tuple[str, ...] = ("point_id",)
) -> pd.DataFrame:
    """Rolling icing-hour counts per point. Ice persists long after conditions pass.

    MEPS runs overlap in valid time, so its rows must be grouped by run as well as by
    point -- otherwise the rolling window runs off the end of one forecast and into a
    different one.
    """
    frame = frame.sort_values([*keys, "valid_time"]).copy()
    grouped = frame.groupby(list(keys)).icing_now
    for window in ICING_WINDOWS_H:
        frame[f"icing_{window}h"] = grouped.transform(
            lambda s, w=window: s.rolling(w, min_periods=1).sum()
        )
    return frame


def aggregate(
    points: pd.DataFrame,
    weights: pd.DataFrame,
    keys: tuple[str, ...] = ("model", "valid_time"),
    dispersion: tuple[str, ...] = ("wind_speed_100m", "power_curve"),
) -> pd.DataFrame:
    """Collapse point features to zonal features, capacity-weighted.

    Spatial dispersion is kept alongside the weighted mean: how much the clusters
    disagree is a cheap, retroactively available uncertainty signal, and it is the main
    thing a single-point representation throws away.

    `keys` exists because the two NWP sources are addressed differently. Open-Meteo rows
    are identified by `(model, valid_time)`; MEPS rows by `(run_time, valid_time)`, since
    consecutive runs overlap and a valid time alone does not name a forecast.
    """
    weight_map = weights.set_index("point_id").weight
    frame = points.copy()
    frame["weight"] = frame.point_id.map(weight_map)

    value_columns = [c for c in frame.columns if c not in {*keys, "point_id", "weight"}]

    def _collapse(group: pd.DataFrame) -> pd.Series:
        weight = group.weight.to_numpy(dtype=float, copy=True)
        weight /= weight.sum()
        values = group[value_columns].to_numpy(dtype=float)
        weighted = np.nansum(values * weight[:, None], axis=0)
        result = dict(zip(value_columns, weighted, strict=True))
        # Dispersion across clusters, for the features where it is physically meaningful.
        for column in dispersion:
            series = group[column].to_numpy(dtype=float)
            finite = series[np.isfinite(series)]
            # A cluster-hour with no finite values happens where a model has a gap;
            # nan is the honest answer, and numpy's all-NaN warnings are just noise.
            if finite.size == 0:
                result[f"{column}_spatial_std"] = np.nan
                result[f"{column}_spatial_range"] = np.nan
            else:
                result[f"{column}_spatial_std"] = float(finite.std())
                result[f"{column}_spatial_range"] = float(finite.max() - finite.min())
        return pd.Series(result)

    return (
        frame.groupby(list(keys)).apply(_collapse, include_groups=False).reset_index()
    )
