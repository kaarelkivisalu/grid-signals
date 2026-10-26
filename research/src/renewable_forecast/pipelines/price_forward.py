"""Publish the declared LEAR forward baseline, preserving historical experiment releases."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from renewable_forecast import paths, publication, windows
from renewable_forecast.models import price as models
from renewable_forecast.pipelines import price
from renewable_forecast.sources import prices

POLICY = paths.CONFIGS / "price_forward.yaml"


def profiles_available(history: pd.Series, delivery: date) -> bool:
    """A 23-hour prior delivery day is complete without a fictitious 02:00 price."""
    hourly = prices.hourly(history)
    return all(
        pd.DatetimeIndex(windows.delivery_day_starts(delivery - timedelta(days=lag)))
        .isin(hourly.index)
        .all()
        for lag in [1, 2, 3, 7]
    )


def publish(delivery: date | None = None) -> pd.DataFrame:
    started = publication.now()
    delivery = delivery or (started.date() + timedelta(days=1))
    issue = delivery - timedelta(days=1)
    policy = yaml.safe_load(POLICY.read_text())
    if policy["model"] != "lear_hourly" or policy["history_days"] != 730:
        raise ValueError("unknown forward price policy")
    history = prices.load()
    frame = prices.features(history)
    complete_hours = prices.hourly(history).index
    train = frame[
        (frame.delivery_day <= pd.Timestamp(issue))
        & (frame.delivery_day >= pd.Timestamp(issue) - pd.Timedelta(days=730))
        & frame.valid_time.dt.floor("h").isin(complete_hours)
    ]
    if train.delivery_day.nunique() < 180:
        raise RuntimeError("LEAR forward publication needs at least 180 training days")
    times = pd.DatetimeIndex(
        windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
    )
    future = prices.features(history, times)
    if not profiles_available(history, delivery):
        raise RuntimeError(
            "LEAR forward publication lacks complete known daily price profiles"
        )
    values = models.ResidualDistribution(models.Lear).fit(train).predict(future)
    if not np.isfinite(values).all():
        raise RuntimeError("non-finite LEAR forward prices")
    rows = future[["valid_time", "delivery_day", "issue_time"]].copy()
    rows["period_end"] = rows.valid_time + pd.Timedelta(minutes=15)
    rows["zone"], rows["fuel_type"], rows["resolution"] = "DE_LU", "spot_price", "15min"
    rows["forecaster"] = "lear_hourly"
    rows["temporal_method"] = "hourly_repeated"
    rows["created_at"] = datetime.now(UTC)
    files = [POLICY, Path(__file__), Path(models.__file__), Path(prices.__file__)]
    fingerprint = b"".join(path.read_bytes() for path in files)
    rows["model_version"] = (
        "price-lear-forward-v1+" + hashlib.sha256(fingerprint).hexdigest()[:12]
    )
    for level, column in zip(models.LEVELS, values.T, strict=True):
        rows[f"eur_mwh_q{level:.2f}"] = column
    return publication.append(
        rows,
        price.VINTAGES,
        started,
        lambda: (
            pd.read_parquet(price.VINTAGES)
            if price.VINTAGES.exists()
            else pd.DataFrame()
        ),
    )


if __name__ == "__main__":
    import json

    from dotenv import load_dotenv

    load_dotenv(paths.ROOT.parent / ".env")
    result = publish()
    print(
        json.dumps(
            {
                "forecast_id": result.forecast_id.iloc[0],
                "status": result.publication_status.iloc[0],
                "forecaster": result.forecaster.iloc[0],
            }
        )
    )
