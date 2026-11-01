"""Calendar, lagged load and archived temperature at a declared information boundary."""

from datetime import date

import numpy as np
import pandas as pd
from dateutil.easter import easter

from grid_signals.forecast import paths, windows
from grid_signals.forecast.sources import load as observations
from grid_signals.forecast.sources import openmeteo

MODEL = "ecmwf_ifs025"
LAGS = (72, 168)
COLUMNS = [
    "load_lag_72",
    "load_lag_168",
    "temperature",
    "heating",
    "cooling",
    "hour_sin",
    "hour_cos",
    "year_sin",
    "year_cos",
    "holiday",
    *[f"dow_{value}" for value in range(7)],
    *[f"quarter_{value}" for value in range(96)],
]


def holidays(year: int) -> set[date]:
    movable = pd.Timestamp(easter(year))
    dates = {
        date(year, 1, 1),
        date(year, 5, 1),
        date(year, 10, 3),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    dates.update(
        (movable + pd.Timedelta(days=offset)).date() for offset in [-2, 1, 39, 50]
    )
    return dates


def calendar(times: pd.DatetimeIndex) -> pd.DataFrame:
    local = times.tz_convert(windows.MARKET_TZ)
    days = local.tz_localize(None).normalize()
    clock = local.hour + local.minute / 60
    known_holidays = set().union(*(holidays(year) for year in set(local.year)))
    data = {
        "valid_time": times,
        "delivery_day": days,
        "issue_time": pd.to_datetime(days - pd.Timedelta(days=1), utc=True)
        + pd.Timedelta(hours=9),
        "hour_sin": np.sin(2 * np.pi * clock / 24),
        "hour_cos": np.cos(2 * np.pi * clock / 24),
        "year_sin": np.sin(2 * np.pi * local.dayofyear / 365.25),
        "year_cos": np.cos(2 * np.pi * local.dayofyear / 365.25),
        "holiday": np.array([day.date() in known_holidays for day in days], dtype=int),
        **{
            f"dow_{value}": (local.dayofweek == value).astype(int) for value in range(7)
        },
        **{
            f"quarter_{value}": (local.hour * 4 + local.minute // 15 == value).astype(
                int
            )
            for value in range(96)
        },
    }
    return pd.DataFrame(data)


def temperature(
    times: pd.DatetimeIndex, issues: pd.Series, raw: pd.DataFrame, points: pd.DataFrame
) -> pd.DataFrame:
    midpoints = times + pd.Timedelta(minutes=7.5)
    left, right = midpoints.floor("h"), midpoints.ceil("h")
    offsets = (
        np.ceil(np.asarray((right - pd.DatetimeIndex(issues)).total_seconds()) / 86400)
        .clip(min=1)
        .astype(int)
    )
    if not np.isin(offsets, openmeteo.OFFSETS).all():
        raise ValueError("temperature information age is outside the archived offsets")
    output = np.zeros(len(times))
    complete = np.ones(len(times), dtype=bool)
    weight = (midpoints - left).total_seconds() / 3600
    for point in points.itertuples():
        sample = (
            raw[(raw.point_id == point.point_id) & (raw.model == MODEL)]
            .set_index("valid_time")
            .sort_index()
        )
        if sample.index.has_duplicates:
            raise ValueError("duplicate temperature forecast intervals")
        a, b = sample.reindex(left), sample.reindex(right)
        values = np.full(len(times), np.nan)
        for offset in openmeteo.OFFSETS:
            mask = offsets == offset
            column = f"temperature_2m_previous_day{offset}"
            values[mask] = (
                a[column].to_numpy()[mask] * (1 - weight[mask])
                + b[column].to_numpy()[mask] * weight[mask]
            )
        complete &= np.isfinite(values)
        output += values * point.weight
    output[~complete] = np.nan
    return pd.DataFrame(
        {
            "temperature": output,
            "nwp_offset_days": offsets,
            "nwp_max_valid_time": right,
            "max_weather_information_time": right - pd.to_timedelta(offsets, unit="D"),
        }
    )


def build(
    history: pd.Series | None = None,
    times: pd.DatetimeIndex | None = None,
    raw: pd.DataFrame | None = None,
) -> pd.DataFrame:
    history = observations.load() if history is None else history
    times = pd.DatetimeIndex(
        observations.native(history).index if times is None else times
    )
    frame = calendar(times)
    for lag in LAGS:
        reference = times - pd.Timedelta(hours=lag)
        values = history.reindex(reference).to_numpy(dtype=float, copy=True)
        available = reference + pd.Timedelta(minutes=15, hours=24)
        values[available > pd.DatetimeIndex(frame.issue_time)] = np.nan
        frame[f"load_lag_{lag}"] = values
    points = pd.read_csv(paths.CONFIGS / "solar_sites.csv")
    if (
        points.point_id.duplicated().any()
        or (points.weight <= 0).any()
        or not np.isclose(points.weight.sum(), 1)
    ):
        raise ValueError(
            "temperature sites need unique IDs and positive weights summing to one"
        )
    weather = temperature(
        times, frame.issue_time, openmeteo.load(MODEL) if raw is None else raw, points
    )
    frame = pd.concat([frame, weather], axis=1)
    frame["heating"] = (15 - frame.temperature).clip(lower=0)
    frame["cooling"] = (frame.temperature - 22).clip(lower=0)
    frame["load"] = history.reindex(times).to_numpy()
    return frame
