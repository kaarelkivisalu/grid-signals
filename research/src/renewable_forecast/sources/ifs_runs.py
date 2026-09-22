"""ECMWF IFS HRES addressed by model run, from the Open-Meteo Single Runs API.

The second run-addressed source, after MEPS. The Previous Runs API used for the main
weather block answers "what did the forecast say N x 24 h before the valid time", which
steps a full day staler at lead hour 34 (`reports/openmeteo_vintage.md`). The Single
Runs API answers "what did the 00z run say" for every lead, which is the question the
task asks.

What was verified against the live API on 2026-09-21:

* `models=ecmwf_ifs` (the 9 km HRES) with `run=YYYY-MM-DDT00:00` is served from
  **2024-03-14**; a 2024-02-15 run is refused. GFS and ICON-EU runs from 2024 are *not*
  served, so this fixes the vintage for ECMWF only.
* Every variable the Previous Runs block uses is present under its plain name.
* Comma-separated coordinates return one payload per point, so a whole run for all
  eight SE3 clusters is one request.

This is a different model from the `ecmwf_ifs025` (0.25 degree) columns in the main
block, so its columns carry their own marker rather than replacing those.

Availability: ECMWF's open-data HRES files for the 00z run appeared 8.57 h after
initialisation before 2025-10-02 and 7.57 h after it (`docs/literature.md`, section 4).
Open-Meteo may receive HRES by another route, but the conservative stamp is the later
figure, 08:35 UTC, which still precedes the 09:00 UTC issue time.
"""

import gzip
import hashlib
import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd

from renewable_forecast import paths

logger = logging.getLogger(__name__)

SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"

MODEL = "ecmwf_ifs"

#: First 00z run the archive serves, bisected against the API.
ARCHIVE_START = date(2024, 3, 14)

RUN_HOUR_UTC = 0

#: Worst measured latency of the 00z HRES open-data files over the backtest window.
#: The leakage guard dates every column to `run_time + AVAILABILITY_LAG`, not to the
#: run instant, because a run cannot be used before it exists.
AVAILABILITY_LAG = timedelta(hours=8, minutes=35)

#: Same names as the Previous Runs block, without the offset suffix.
VARIABLES = (
    "wind_speed_100m",
    "wind_speed_10m",
    "wind_direction_100m",
    "wind_gusts_10m",
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
    "snow_depth",
    "precipitation",
)

#: Delivery hours sit at +22..+46 from the 00z run. Six earlier steps feed the rolling
#: and icing-memory features, and a few later ones feed the forward shifts. Mirrors
#: `meps.LEAD_FIRST`/`LEAD_LAST`.
LEAD_FIRST = 16
FORECAST_HOURS = 54

#: Open-Meteo's free tier limits calls per minute and per hour, and an eight-location,
#: nine-variable request counts as several calls. The first backfill hit HTTP 429 at
#: about 13 runs a minute; this pace and the long backoff keep it under the limits.
_MIN_INTERVAL_S = 3.0
_MAX_RETRIES = 8
_RETRYABLE = {429, 500, 502, 503, 504}


#: The previous day's 18z run, a time-lagged partner for the 00z run. Run-to-run change
#: between consecutive cycles is a flow-dependent uncertainty signal that needs no
#: ensemble archive. The 18z HRES open-data files arrive ~6.5 h after initialisation,
#: i.e. about 00:30 UTC on the issue day.
LAGGED_RUN_HOUR_UTC = 18


def runs(start: date, end: date, run_hour: int = RUN_HOUR_UTC) -> Iterator[datetime]:
    """The run instants at `run_hour` over a half-open date range."""
    cursor = max(start, ARCHIVE_START)
    while cursor < end:
        yield datetime(cursor.year, cursor.month, cursor.day, run_hour, tzinfo=UTC)
        cursor += timedelta(days=1)


def params_for(run: datetime, points: pd.DataFrame) -> dict:
    """Request parameters for one run over every point, in point order.

    The horizon is set so that every run reaches the end of the delivery window plus
    the forward shifts: +53 h from 00z, so +59 h from the previous day's 18z.
    """
    return {
        "latitude": ",".join(f"{v:.4f}" for v in points.latitude),
        "longitude": ",".join(f"{v:.4f}" for v in points.longitude),
        "models": MODEL,
        "run": run.strftime("%Y-%m-%dT%H:%M"),
        "hourly": ",".join(VARIABLES),
        "forecast_hours": FORECAST_HOURS + (24 - run.hour) % 24,
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }


def _raw_path(params: dict) -> Path:
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    return paths.RAW / "ifs_runs" / f"{digest[:20]}.json.gz"


def fetch(client: httpx.Client, params: dict) -> list[dict]:
    """Fetch one run, serving from the raw archive when already downloaded."""
    path = _raw_path(params)
    if path.exists():
        with gzip.open(path, "rt") as handle:
            return json.load(handle)

    delay = 60.0
    for attempt in range(1, _MAX_RETRIES + 1):
        response = client.get(SINGLE_RUNS_URL, params=params)
        if response.status_code == 200:
            payload = response.json()
            payload = payload if isinstance(payload, list) else [payload]
            path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, "wt") as handle:
                json.dump(payload, handle)
            time.sleep(_MIN_INTERVAL_S)
            return payload
        if response.status_code == 400:
            # The API answers 400 with a reason for a run it does not hold. That is a
            # gap in the archive, not a failure of the pull.
            msg = response.json().get("reason", response.text)
            raise ValueError(msg)
        if response.status_code not in _RETRYABLE or attempt == _MAX_RETRIES:
            response.raise_for_status()
        logger.warning("HTTP %s, retrying in %.0fs", response.status_code, delay)
        time.sleep(delay)
        delay *= 2
    msg = "unreachable"
    raise AssertionError(msg)


def parse(payload: list[dict], run: datetime, points: pd.DataFrame) -> pd.DataFrame:
    """One run's payload to long rows keyed by `(run_time, valid_time, point_id)`."""
    if len(payload) != len(points):
        msg = f"expected {len(points)} locations, got {len(payload)}"
        raise ValueError(msg)
    frames = []
    for location, point_id in zip(payload, points.point_id, strict=True):
        frame = pd.DataFrame(location["hourly"])
        frame["valid_time"] = pd.to_datetime(frame.pop("time"), utc=True)
        for column in VARIABLES:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["point_id"] = point_id
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    out["run_time"] = pd.Timestamp(run)
    lead = (out.valid_time - out.run_time).dt.total_seconds() / 3600
    return out[lead >= LEAD_FIRST].reset_index(drop=True)


def _run_path(run: datetime) -> Path:
    return paths.PARSED / "ifs_runs" / f"run={run:%Y%m%dT%H}Z" / "data.parquet"


def pull(
    points: pd.DataFrame, start: date, end: date, run_hour: int = RUN_HOUR_UTC
) -> int:
    """Backfill every run at `run_hour` over a date range, one parquet per run."""
    written, missing = 0, []
    with httpx.Client(timeout=120.0) as client:
        for run in runs(start, end, run_hour):
            out = _run_path(run)
            if out.exists():
                continue
            try:
                frame = parse(fetch(client, params_for(run, points)), run, points)
            except ValueError as error:
                missing.append(f"{run:%Y-%m-%d}")
                logger.warning("run %s unavailable: %s", run.date(), error)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(out, index=False)
            written += 1
            if written % 50 == 0:
                logger.info("%s runs written, at %s", written, run.date())
    if missing:
        logger.warning("%s runs unavailable: %s", len(missing), ", ".join(missing))
    return written


def load() -> pd.DataFrame:
    """Read the parsed store back."""
    files = sorted((paths.PARSED / "ifs_runs").glob("run=*/data.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
