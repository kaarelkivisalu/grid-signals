"""Open-Meteo Previous Runs: archived forecasts at a fixed information age.

`<var>_previous_dayN` is the value that was available N x 24 h before the valid time.
That is *not* the same as "the 00z run of day D", which is what the task actually uses,
but it is the closest retroactively available approximation -- see
`reports/openmeteo_vintage.md` for the measured semantics and the bias it implies.

Blends such as `best_match` are deliberately never requested: their composition changes
over time, which is a silent non-stationarity in a training set.
"""

import gzip
import hashlib
import json
import logging
import time
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from renewable_forecast import paths

logger = logging.getLogger(__name__)

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

#: Pinned deterministic models. Only these three have a consistent archive back to
#: early 2024; dmi_harmonie_arome_europe and knmi_harmonie_arome_europe carry recent
#: data only, and adding them would make the feature set non-stationary.
MODELS = ("ecmwf_ifs025", "gfs025", "icon_eu")

#: Measured archive start per model (bisected against the API).
ARCHIVE_START = {
    "ecmwf_ifs025": date(2024, 3, 6),
    "gfs025": date(2024, 2, 16),
    "icon_eu": date(2024, 2, 16),
}

#: Both offsets are fetched for every variable, because neither alone is usable.
#: A forecast issued 09:00 UTC on day D for delivery on D+1 needs an information age of
#: 14-37 h across the delivery day. `previous_day1` (24 h) is legitimate for only the
#: first 11 hours; using it beyond that would consume data that did not exist at issue
#: time. `previous_day2` (48 h) is always legitimate but needlessly stale early on. The
#: design matrix therefore picks the smallest safe offset per target hour.
OFFSETS = (1, 2)

#: One offset staler than any that can be *chosen*, fetched for wind speed alone so the
#: error-growth feature compares chosen-vs-staler for every row. Fetching all variables
#: at this offset would inflate the payload for no gain.
SPREAD_ONLY_OFFSET = 3

WIND_VARIABLES = (
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

_CHUNK_DAYS = 120
#: Open-Meteo weights a request by variables x days, so a 120-day multi-variable pull
#: costs far more than one unit. Pace deliberately rather than leaning on backoff.
_MIN_INTERVAL_S = 4.0
_MAX_RETRIES = 4


def _hourly_fields(
    variables: tuple[str, ...], offsets: tuple[int, ...] = OFFSETS
) -> str:
    return ",".join(f"{v}_previous_day{o}" for o in offsets for v in variables)


def _request_hash(params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def _raw_path(digest: str) -> Path:
    return paths.RAW / "openmeteo" / f"{digest}.json.gz"


def chunks(
    start: date, end: date, days: int = _CHUNK_DAYS
) -> Iterator[tuple[date, date]]:
    """Split a date range into chunks of at most `days` days."""
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=days), end)
        yield cursor, stop
        cursor = stop


def fetch(client: httpx.Client, params: dict) -> dict:
    """Fetch one request, serving from the raw archive when already downloaded.

    The raw response is stored verbatim under a hash of its parameters, so re-parsing
    costs no API calls and an interrupted pull resumes for free.
    """
    digest = _request_hash(params)
    path = _raw_path(digest)
    if path.exists():
        with gzip.open(path, "rt") as handle:
            return json.load(handle)

    delay = 20.0
    for attempt in range(1, _MAX_RETRIES + 1):
        response = client.get(PREVIOUS_RUNS_URL, params=params)
        if response.status_code == 200:
            payload = response.json()
            path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, "wt") as handle:
                json.dump(payload, handle)
            time.sleep(_MIN_INTERVAL_S)
            return payload
        if (
            response.status_code not in {429, 500, 502, 503, 504}
            or attempt == _MAX_RETRIES
        ):
            response.raise_for_status()
        logger.warning("HTTP %s, retrying in %.0fs", response.status_code, delay)
        time.sleep(delay)
        delay *= 2
    msg = "unreachable"
    raise AssertionError(msg)


def _parse(payload: dict, point_id: str, model: str) -> pd.DataFrame:
    hourly = payload.get("hourly", {})
    if not hourly:
        return pd.DataFrame()
    frame = pd.DataFrame(hourly)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.rename(columns={"time": "valid_time"})
    frame["point_id"] = point_id
    frame["model"] = model
    return frame


def pull(
    points: pd.DataFrame,
    start: date,
    end: date,
    models: tuple[str, ...] = MODELS,
    variables: tuple[str, ...] = WIND_VARIABLES,
    offsets: tuple[int, ...] = OFFSETS,
) -> pd.DataFrame:
    """Fetch every point x model x chunk, writing parsed parquet per point and model."""
    fields = _hourly_fields(variables, offsets)
    collected: list[pd.DataFrame] = []
    with httpx.Client(timeout=120.0) as client:
        for model in models:
            model_start = max(start, ARCHIVE_START.get(model, start))
            for _, point in points.iterrows():
                frames = []
                for chunk_start, chunk_end in chunks(model_start, end):
                    params = {
                        "latitude": float(point.latitude),
                        "longitude": float(point.longitude),
                        "start_date": chunk_start.isoformat(),
                        "end_date": (chunk_end - timedelta(days=1)).isoformat(),
                        "hourly": fields,
                        "models": model,
                        "wind_speed_unit": "ms",
                        "timezone": "UTC",
                    }
                    frames.append(_parse(fetch(client, params), point.point_id, model))
                merged = pd.concat(
                    [f for f in frames if not f.empty], ignore_index=True
                )
                out = (
                    paths.PARSED
                    / "openmeteo"
                    / f"model={model}"
                    / f"point={point.point_id}"
                    / "data.parquet"
                )
                out.parent.mkdir(parents=True, exist_ok=True)
                merged.to_parquet(out, index=False)
                collected.append(merged)
                logger.info("%s %s: %s rows", model, point.point_id, len(merged))
    return pd.concat(collected, ignore_index=True)


def load(model: str | None = None) -> pd.DataFrame:
    """Read the parsed NWP store back."""
    root = paths.PARSED / "openmeteo"
    pattern = f"model={model}/**/*.parquet" if model else "model=*/**/*.parquet"
    files = sorted(root.glob(pattern))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
