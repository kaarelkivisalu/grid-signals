"""SDAC price targets, retaining the hourly-to-quarter-hour boundary explicitly."""

from datetime import date

import pandas as pd

from renewable_forecast import windows
from renewable_forecast.sources import entsoe

NATIVE_START = pd.Timestamp("2025-10-01", tz=windows.MARKET_TZ).tz_convert("UTC")


def load() -> pd.Series:
    raw = entsoe.load("day_ahead_prices", "DE_LU")
    if raw.empty:
        raise RuntimeError("No DE-LU price history is cached")
    raw["period_start"] = pd.to_datetime(raw.period_start, utc=True)
    raw = raw.sort_values("fetched_at").drop_duplicates("period_start", keep="last")
    return raw.set_index("period_start").value_mw.sort_index().rename("price")


def refresh(start: date, stop: date) -> str:
    # entsoe-py 0.7.11 explicitly requests classification sequence 1 for DE-LU:
    # SDAC, rather than the separate EXAA auction.
    return entsoe.fetch_chunk(entsoe.client(), "day_ahead_prices", "DE_LU", start, stop)


def hourly(series: pd.Series) -> pd.Series:
    values = series.resample("h").mean()
    count = series.resample("h").count()
    required = pd.Series(1, index=count.index)
    required.loc[required.index >= NATIVE_START] = 4
    return values[count == required]


def native(series: pd.Series) -> pd.Series:
    series = series[series.index >= NATIVE_START]
    count = series.groupby(series.index.floor("h")).transform("size")
    return series[count == 4]


def features(history: pd.Series, times: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    times = pd.DatetimeIndex(history.index if times is None else times)
    local = times.tz_convert(windows.MARKET_TZ)
    days = local.tz_localize(None).normalize()
    out = pd.DataFrame(
        {"valid_time": times, "delivery_day": days, "local_hour": local.hour},
        index=times,
    )
    out["issue_time"] = pd.to_datetime(
        days - pd.Timedelta(days=1), utc=True
    ) + pd.Timedelta(hours=9)
    for lag in [24, 48, 72, 168]:
        reference = times - pd.Timedelta(hours=lag)
        values = history.reindex(reference).to_numpy(dtype=float, copy=True)
        # A UTC 24-hour lag can reach the delivery day on a 25-hour local day.
        # That auction curve was not yet known at the pre-auction cutoff.
        published = (
            reference.tz_convert(windows.MARKET_TZ).tz_localize(None).normalize()
            - pd.Timedelta(days=1)
            + pd.Timedelta(hours=12)
        )
        published = published.tz_localize(windows.MARKET_TZ).tz_convert("UTC")
        values[published > pd.DatetimeIndex(out.issue_time)] = float("nan")
        out[f"p_lag_{lag}"] = values
    profiles = hourly(history).rename("price").to_frame()
    profiles["delivery_day"] = (
        profiles.index.tz_convert(windows.MARKET_TZ).tz_localize(None).normalize()
    )
    profiles["hour"] = profiles.index.tz_convert(windows.MARKET_TZ).hour
    daily = (
        profiles.groupby(["delivery_day", "hour"])
        .price.mean()
        .unstack("hour")
        .reindex(columns=range(24))
    )
    for lag in [1, 2, 3, 7]:
        lagged = daily.reindex(days - pd.Timedelta(days=lag))
        for hour in range(24):
            out[f"profile_d{lag}_h{hour:02d}"] = lagged[hour].to_numpy()
    for weekday in range(7):
        out[f"dow_{weekday}"] = (local.dayofweek == weekday).astype(int)
    out["quarter"] = local.hour * 4 + local.minute // 15
    out["month"] = local.month
    out["price"] = history.reindex(times).to_numpy()
    out["native"] = times >= NATIVE_START
    return out.reset_index(drop=True)
