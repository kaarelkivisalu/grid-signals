"""ENTSO-E Transparency Platform ingestion into local parquet.

Self-contained on purpose: this project re-pulls rather than reading the grid-signals
database, because it needs A69 and A68 (which that database does not hold) and because
it needs control over forecast vintages.

Each request's result is cached as one parquet file keyed by dataset/zone/chunk, so a
parser change costs zero API calls and an interrupted backfill resumes for free. A
zero-byte `.empty` sentinel marks "the API answered, there is genuinely no data here",
which is distinct from "not fetched yet".
"""

import logging
import os
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests.exceptions
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError

from renewable_forecast import paths

logger = logging.getLogger(__name__)

#: Bidding zone (or country, for datasets published nationally) -> entsoe-py code.
ZONE_TO_ENTSOE = {
    "SE1": "SE_1",
    "SE2": "SE_2",
    "SE3": "SE_3",
    "SE4": "SE_4",
    "SE": "SE",
    "DE_LU": "DE_LU",
}

#: Which areas each dataset is published for. A68 installed capacity is published at
#: *country* level for Sweden -- SE_1..SE_4 all return NoMatchingDataError -- so the
#: capacity level check is national, and Vindbrukskollen supplies the SE3 split.
DATASET_ZONES = {
    "actual_generation": ["SE1", "SE2", "SE3", "SE4", "DE_LU"],
    "da_wind_solar_forecast": ["SE1", "SE2", "SE3", "SE4", "DE_LU"],
    "installed_capacity": ["SE", "DE_LU"],
    "day_ahead_prices": ["SE3", "DE_LU"],
}

#: ENTSO-E allows 400 requests/minute; stay well under it.
_REQUESTS_PER_MINUTE = 200
_CHUNK_DAYS = 90
_MAX_RETRIES = 3
_INITIAL_DELAY_S = 5

#: The market operates in CET/CEST; ENTSO-E expects local timestamps.
_MARKET_TZ = "Europe/Brussels"


class _RateLimiter:
    """Token bucket shared across worker threads."""

    def __init__(self, per_minute: int) -> None:
        self._interval = 60.0 / per_minute
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        """Block until the next request is allowed."""
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if wait:
            time.sleep(wait)


_limiter = _RateLimiter(_REQUESTS_PER_MINUTE)


def client() -> EntsoePandasClient:
    """Build a client from ENTSOE_API_KEY in the environment."""
    key = os.environ.get("ENTSOE_API_KEY")
    if not key:
        msg = "ENTSOE_API_KEY is not set; load the repository .env first"
        raise RuntimeError(msg)
    return EntsoePandasClient(api_key=key, retry_count=1, timeout=120)


def chunks(
    start: date, end: date, days: int = _CHUNK_DAYS
) -> Iterator[tuple[date, date]]:
    """Split a date range into half-open chunks of at most `days` days."""
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=days), end)
        yield cursor, stop
        cursor = stop


def _cache_path(dataset: str, zone: str, start: date, stop: date) -> Path:
    return (
        paths.RAW
        / "entsoe"
        / f"dataset={dataset}"
        / f"zone={zone}"
        / f"{start:%Y%m%d}_{stop:%Y%m%d}.parquet"
    )


def _retry(fn, *args, **kwargs):
    """Call `fn`, retrying transient 5xx responses with exponential back-off."""
    delay = _INITIAL_DELAY_S
    for attempt in range(1, _MAX_RETRIES + 1):
        _limiter.acquire()
        try:
            return fn(*args, **kwargs)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is None or status < 500 or attempt == _MAX_RETRIES:
                raise
            logger.warning("HTTP %s, retrying in %ss", status, delay)
            time.sleep(delay)
            delay *= 2
        except requests.exceptions.ConnectionError:
            if attempt == _MAX_RETRIES:
                raise
            logger.warning("connection error, retrying in %ss", delay)
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def _to_long(frame: pd.DataFrame | pd.Series, value_name: str) -> pd.DataFrame:
    """Normalise an entsoe-py result to long format with a UTC period_start."""
    if isinstance(frame, pd.Series):
        frame = frame.to_frame(name=value_name)
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame.index.name = "period_start"

    if isinstance(frame.columns, pd.MultiIndex):
        # (fuel_type, aggregation) -> keep both; callers filter on aggregation.
        frame.columns = pd.MultiIndex.from_tuples(
            [(str(a), str(b)) for a, b in frame.columns],
            names=["fuel_type", "aggregation"],
        )
        long = frame.stack(["fuel_type", "aggregation"], future_stack=True)
        long = long.rename(value_name).reset_index()
    else:
        frame.columns = [str(c) for c in frame.columns]
        frame.columns.name = "fuel_type"
        long = frame.stack(future_stack=True).rename(value_name).reset_index()
        long["aggregation"] = "Actual Aggregated"

    return long.dropna(subset=[value_name])


_FETCHERS = {
    # A75 actual generation per production type -- the target.
    "actual_generation": lambda c, z, s, e: c.query_generation(z, start=s, end=e),
    # A69 day-ahead wind & solar forecast -- the benchmark to beat.
    "da_wind_solar_forecast": lambda c, z, s, e: c.query_wind_and_solar_forecast(
        z, start=s, end=e, process_type="A01"
    ),
    # A68 installed generation capacity -- authoritative on capacity level.
    "installed_capacity": lambda c, z, s, e: c.query_installed_generation_capacity(
        z, start=s, end=e
    ),
    # A44 day-ahead prices -- only used to flag hours where curtailment is plausible.
    "day_ahead_prices": lambda c, z, s, e: c.query_day_ahead_prices(z, start=s, end=e),
}


def fetch_chunk(
    cli: EntsoePandasClient, dataset: str, zone: str, start: date, stop: date
) -> str:
    """Fetch one chunk into the parquet cache. Returns 'cached', 'empty' or 'fetched'."""
    out = _cache_path(dataset, zone, start, stop)
    sentinel = out.with_suffix(".empty")
    if out.exists() or sentinel.exists():
        return "cached"

    ts_start = pd.Timestamp(start, tz=_MARKET_TZ)
    ts_stop = pd.Timestamp(stop, tz=_MARKET_TZ)
    try:
        raw = _retry(_FETCHERS[dataset], cli, ZONE_TO_ENTSOE[zone], ts_start, ts_stop)
    except NoMatchingDataError:
        out.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        return "empty"

    long = _to_long(raw, "value_mw")
    if long.empty:
        out.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        return "empty"

    long["zone"] = zone
    long["fetched_at"] = datetime.now(tz=pd.Timestamp.utcnow().tz)
    out.parent.mkdir(parents=True, exist_ok=True)
    long.to_parquet(out, index=False)
    return "fetched"


def backfill(
    datasets: list[str],
    start: date,
    end: date,
    zones: dict[str, list[str]] | None = None,
    workers: int = 4,
) -> dict[str, int]:
    """Fetch every missing chunk. Safe to interrupt and re-run."""
    cli = client()
    per_dataset = zones or DATASET_ZONES
    jobs = [
        (dataset, zone, chunk_start, chunk_stop)
        for dataset in datasets
        # A68 is an annual snapshot, so one request per calendar year is enough.
        for chunk_days in [366 if dataset == "installed_capacity" else _CHUNK_DAYS]
        for zone in per_dataset[dataset]
        for chunk_start, chunk_stop in chunks(start, end, chunk_days)
    ]
    tally: dict[str, int] = {"cached": 0, "empty": 0, "fetched": 0, "failed": 0}

    def run(job) -> str:
        try:
            return fetch_chunk(cli, *job)
        except Exception:
            logger.exception("failed: %s", job)
            return "failed"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, outcome in enumerate(pool.map(run, jobs), start=1):
            tally[outcome] += 1
            if i % 25 == 0 or i == len(jobs):
                logger.info("%s/%s chunks -- %s", i, len(jobs), tally)
    return tally


def load(dataset: str, zone: str | None = None) -> pd.DataFrame:
    """Read every cached chunk of a dataset back into one long DataFrame."""
    root = paths.RAW / "entsoe" / f"dataset={dataset}"
    pattern = f"zone={zone}/*.parquet" if zone else "zone=*/*.parquet"
    files = sorted(root.glob(pattern))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
