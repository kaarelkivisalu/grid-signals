"""DE-LU solar: archived irradiance -> tilted PV output -> quarter-hour features.

The initial fleet uses a configurable equal-area lattice, a declared orientation mix,
and annual A68 capacity snapshots. These are explicit approximations until a dated
MaStR fleet is supplied; none is inferred from held-out generation.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pvlib

from renewable_forecast import config, paths, windows
from renewable_forecast.features import assemble
from renewable_forecast.features.resolution import validate
from renewable_forecast.sources import entsoe, openmeteo
from renewable_forecast.targets import actuals

MODEL = "ecmwf_ifs025"
VARIABLES = ("shortwave_radiation_instant", "temperature_2m", "snow_depth")
# (tilt degrees, azimuth degrees clockwise from north, fleet share).
ORIENTATIONS = ((30.0, 180.0, 0.5), (20.0, 90.0, 0.25), (20.0, 270.0, 0.25))
DAYLIGHT_ELEVATION = 5.0


def sites() -> pd.DataFrame:
    """The declared spatial approximation, independent of observed output."""
    filename = config.load("delu_solar").features.get("solar_sites", "solar_sites.csv")
    points = pd.read_csv(paths.CONFIGS / filename)
    if (
        points.point_id.duplicated().any()
        or (points.weight <= 0).any()
        or not np.isclose(points.weight.sum(), 1)
    ):
        raise ValueError(
            "solar sites must be unique with positive weights summing to one"
        )
    return points


def capacity_snapshots() -> pd.Series:
    """Annual published capacity, resolving chunk-boundary carryovers explicitly.

    The same timestamp can contain the preceding year's carried-forward value. The
    largest value is the new annual snapshot for this growing fleet. Dates stay as
    published: future snapshots never enter interpolation or extrapolation.
    """
    raw = entsoe.load("installed_capacity", "DE_LU")
    if raw.empty:
        raise RuntimeError("no DE-LU A68 capacity cached")
    raw = raw[raw.fuel_type.map(actuals.slug) == "solar"].copy()
    if raw.empty:
        raise RuntimeError("no DE-LU solar A68 capacity cached")
    raw["period_start"] = pd.to_datetime(raw.period_start, utc=True)
    return raw.groupby("period_start").value_mw.max().sort_index()


def capacity_at(times: pd.Series) -> np.ndarray:
    """Last annual snapshot at issue time; no use of a future year-end anchor."""
    snapshots = capacity_snapshots()
    index = pd.DatetimeIndex(times)
    positions = snapshots.index.get_indexer(index, method="ffill")
    values = np.where(
        positions >= 0, snapshots.to_numpy()[np.maximum(positions, 0)], np.nan
    )
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("no positive solar capacity known at issue time")
    return values


def pv_output(
    ghi: np.ndarray,
    temperature: np.ndarray,
    times: pd.DatetimeIndex,
    latitude: float,
    longitude: float,
) -> tuple[np.ndarray, np.ndarray]:
    """PVWatts DC with a fixed orientation mix and explicit nominal losses."""
    position = pvlib.solarposition.get_solarposition(times, latitude, longitude)
    zenith = position.apparent_zenith.to_numpy()
    radiation = pvlib.irradiance.erbs(ghi, zenith, times)
    output = np.zeros(len(times))
    for tilt, azimuth, share in ORIENTATIONS:
        plane = pvlib.irradiance.get_total_irradiance(
            tilt,
            azimuth,
            zenith,
            position.azimuth,
            radiation.dni,
            ghi,
            radiation.dhi,
        ).poa_global.to_numpy()
        cell_temperature = temperature + 0.03 * plane
        output += share * pvlib.pvsystem.pvwatts_dc(
            plane, cell_temperature, 1.0, -0.004
        )
    output = np.clip(output * 0.86, 0, 1)
    output[zenith >= 90] = 0.0
    return output, 90 - zenith


def weather_block(
    raw: pd.DataFrame, points: pd.DataFrame, offset: int, resolution: str = "15min"
) -> pd.DataFrame:
    """Interpolate clear-sky index, rather than irradiance, through dawn and dusk.

    Instantaneous radiation avoids the provider's backwards-hour-mean convention.
    Evaluate the physical chain at interval midpoints. This approximates interval mean
    MW; it is not a claim that NWP resolves sub-hourly clouds.
    """
    step = validate(resolution)
    collected = []
    for point in points.itertuples():
        sample = raw[
            (raw.point_id == point.point_id) & (raw.model == MODEL)
        ].sort_values("valid_time")
        if sample.empty:
            raise RuntimeError(f"no solar NWP for {point.point_id}")
        source_times = pd.DatetimeIndex(sample.valid_time)
        location = pvlib.location.Location(point.latitude, point.longitude)
        source_clear = location.get_clearsky(source_times).ghi.to_numpy()
        ghi = sample[f"shortwave_radiation_instant_previous_day{offset}"].to_numpy(
            dtype=float
        )
        index = np.divide(
            ghi, source_clear, out=np.zeros(len(ghi)), where=source_clear > 10
        )
        index[~np.isfinite(ghi)] = np.nan
        # Night has no meaningful ratio. Use a fixed clear-sky boundary value rather
        # than borrowing a later daylight forecast with a different information age.
        daylight = (source_clear > 10) & np.isfinite(index)
        if not daylight.any():
            raise RuntimeError(f"no usable solar radiation for {point.point_id}")
        night = (source_clear <= 10) & np.isfinite(ghi)
        index[night] = 1.0
        starts = pd.date_range(source_times.min(), source_times.max() - step, freq=step)
        midpoints = starts + step / 2
        x, target = source_times.asi8, midpoints.asi8
        right = np.searchsorted(x, target)
        left = np.maximum(right - 1, 0)
        right = np.minimum(right, len(x) - 1)
        complete = (x[right] - x[left]) <= pd.Timedelta("1h").value
        clear = location.get_clearsky(midpoints).ghi.to_numpy()
        interpolated_index = np.clip(np.interp(target, x, index), 0, 1.5)
        interpolated_index[~complete] = np.nan
        temperature = np.interp(
            target, x, sample[f"temperature_2m_previous_day{offset}"]
        )
        irradiance = clear * interpolated_index
        power, elevation = pv_output(
            irradiance, temperature, midpoints, point.latitude, point.longitude
        )
        clear_power, _ = pv_output(
            clear.to_numpy() if isinstance(clear, pd.Series) else clear,
            np.full(len(clear), 20.0),
            midpoints,
            point.latitude,
            point.longitude,
        )
        snow = np.interp(target, x, sample[f"snow_depth_previous_day{offset}"])
        collected.append(
            pd.DataFrame(
                {
                    "valid_time": starts,
                    "physical_cf": power * point.weight,
                    "clear_sky_cf": clear_power * point.weight,
                    "ghi": irradiance * point.weight,
                    "temperature_2m": temperature * point.weight,
                    "snow_flag": (snow > 0.01).astype(float) * point.weight,
                    "solar_elevation": elevation,
                }
            )
        )
    all_points = pd.concat(collected, ignore_index=True)
    grouped = all_points.groupby("valid_time")
    columns = ["physical_cf", "clear_sky_cf", "ghi", "temperature_2m", "snow_flag"]
    # min_count enforces spatial completeness: an absent region is not zero sunshine.
    block = grouped[columns].sum(min_count=len(points))
    block["solar_elevation"] = grouped.solar_elevation.max()
    block["nwp_offset_days"] = offset
    return block.reset_index()


def build(delivery_day: date | None = None, resolution: str = "15min") -> pd.DataFrame:
    """Native-resolution training matrix or one future delivery day."""
    step = validate(resolution)
    raw = openmeteo.load(MODEL)
    points = sites()
    if raw.empty:
        raise RuntimeError("no solar weather cached; run pipelines.pull_solar first")
    raw = raw[raw.point_id.isin(points.point_id)]
    if raw.empty:
        raise RuntimeError("no solar weather cached; run pipelines.pull_solar first")
    if delivery_day is not None:
        first = pd.Timestamp(windows.delivery_day_starts(delivery_day)[0])
        raw = raw[
            raw.valid_time.between(
                first - pd.Timedelta(days=1), first + pd.Timedelta(days=2)
            )
        ]
        target = pd.DataFrame(
            {"valid_time": windows.delivery_day_starts(delivery_day, resolution=step)}
        )
    else:
        observed_raw = entsoe.load("actual_generation", "DE_LU")
        observed_raw = observed_raw[observed_raw.fuel_type.map(actuals.slug) == "solar"]
        observations = actuals.to_quarter_hourly(observed_raw)
        observations = observations[observations.fuel_type == "solar"]
        if step == pd.Timedelta("1h"):
            observations = (
                observations.set_index("period_start")
                .mw.resample("h")
                .agg(["mean", "count"])
            )
            observations = (
                observations[observations["count"] == 4][["mean"]]
                .rename(columns={"mean": "mw"})
                .reset_index()
            )
        target = observations.rename(columns={"period_start": "valid_time"})[
            ["valid_time", "mw"]
        ].copy()
    target = assemble._annotate(target)  # noqa: SLF001
    # Midpoint CSI uses the following hourly instant, whose archive value must also
    # predate issue. No temporal lookahead features are used in this solar model.
    target["nwp_offset_days"] = assemble.required_offset(
        (target.valid_time + step / 2).dt.ceil("h"), assemble.issue_time_of(target)
    )
    target["nwp_max_valid_time"] = (target.valid_time + step / 2).dt.ceil("h")
    target["capacity_mw"] = capacity_at(assemble.issue_time_of(target))
    if "mw" in target:
        target["cf"] = target.mw / target.capacity_mw
        target = target[target.cf.between(0, 1)].copy()
    stacked = pd.concat(
        [
            weather_block(raw, points, offset, resolution)
            for offset in openmeteo.OFFSETS
        ],
        ignore_index=True,
    )
    frame = target.merge(
        stacked,
        on=["valid_time", "nwp_offset_days"],
        how="left" if delivery_day else "inner",
    )
    frame = pd.concat([frame, assemble.calendar(frame)], axis=1)
    return frame.sort_values("valid_time").reset_index(drop=True)


def refresh(delivery_day: date) -> None:
    """Archive both required information-age offsets for a live forecast."""
    openmeteo.pull(
        sites(),
        delivery_day - timedelta(days=1),
        delivery_day + timedelta(days=2),
        models=(MODEL,),
        variables=VARIABLES,
        merge=True,
    )
