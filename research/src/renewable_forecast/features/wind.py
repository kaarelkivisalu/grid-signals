"""Wind features: physics first, statistics second.

The power-curve transform is the highest-value feature here, and the order of operations
matters: transform **per cluster, then capacity-weight**. The curve is convex below rated
and concave above, so transforming a spatial mean discards exactly the smoothing that
makes zonal capacity factor far less peaky than point capacity factor.
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


def add_icing_memory(frame: pd.DataFrame) -> pd.DataFrame:
    """Rolling icing-hour counts per point. Ice persists long after conditions pass."""
    frame = frame.sort_values(["point_id", "valid_time"]).copy()
    grouped = frame.groupby("point_id").icing_now
    for window in ICING_WINDOWS_H:
        frame[f"icing_{window}h"] = grouped.transform(
            lambda s, w=window: s.rolling(w, min_periods=1).sum()
        )
    return frame


def aggregate(points: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """Collapse point features to zonal features, capacity-weighted.

    Spatial dispersion is kept alongside the weighted mean: how much the clusters
    disagree is a cheap, retroactively available uncertainty signal, and it is the main
    thing a single-point representation throws away.
    """
    weight_map = weights.set_index("point_id").weight
    frame = points.copy()
    frame["weight"] = frame.point_id.map(weight_map)

    value_columns = [
        c
        for c in frame.columns
        if c not in {"valid_time", "point_id", "model", "weight"}
    ]

    def _collapse(group: pd.DataFrame) -> pd.Series:
        weight = group.weight.to_numpy(dtype=float, copy=True)
        weight /= weight.sum()
        values = group[value_columns].to_numpy(dtype=float)
        weighted = np.nansum(values * weight[:, None], axis=0)
        result = dict(zip(value_columns, weighted, strict=True))
        # Dispersion across clusters, for the features where it is physically meaningful.
        for column in ("wind_speed_100m", "power_curve"):
            series = group[column].to_numpy(dtype=float)
            result[f"{column}_spatial_std"] = float(np.nanstd(series))
            result[f"{column}_spatial_range"] = float(
                np.nanmax(series) - np.nanmin(series)
            )
        return pd.Series(result)

    return (
        frame.groupby(["model", "valid_time"])
        .apply(_collapse, include_groups=False)
        .reset_index()
    )
