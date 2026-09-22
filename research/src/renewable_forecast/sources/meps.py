"""MET Norway MEPS: NWP addressed by model run rather than by whole days.

Open-Meteo's Previous Runs API can only be asked for values *as they stood N x 24 h
before the valid time*, which is not the same question as "what did the 00z run say".
The consequence is measured and large: the back half of every delivery day is served by
a forecast a full day staler than the run we actually held, worth a +35% step in nMAE at
lead hour 34 (`reports/openmeteo_vintage.md`).

MEPS files on thredds.met.no are addressed by run initialisation. One 00z run covers the
whole +22..+47 h delivery window, so the step disappears by construction rather than by
correction.

Two things make this cheap and stable:

* **Product stability.** `meps_det_hl` is present at 00z every day from 2024-01 through
  2026-09 with an identical signature -- 949 x 1069 grid at 2.5 km, 67 hourly lead
  steps, heights [80, 120] m, same four variables. The archive's *other* products do
  churn (see `reports/meps_archive.md`); this one does not, which is why it is the one
  used. Era drift was the headline risk in the Phase 6 spike and the chosen product
  sidesteps it entirely.
* **Chunking.** The variables are chunked `[1, 2, 1069, 949]` -- one full horizontal
  slice per lead step. The server therefore decompresses an entire domain slice whether
  a request asks for one grid cell or a whole region, so the cost it bears scales with
  the number of *requests*, not with the bytes returned. Asking for the eight cluster
  points separately would make it do the same decompression eight times over; asking
  once for the bounding box that contains them makes it do the work once. That is both
  ~8x less load on a shared public service and ~4.6x faster, at the price of
  transferring a box we mostly discard.

Two decode paths exist on purpose. `fetch_run` pulls the bounding box over the binary
protocol and is what the backfill uses. `fetch_point_ascii` pulls a single cell over the
text protocol, and exists so `tests/test_meps.py` can confirm -- against the live
archive, through entirely separate code -- that the box is being indexed correctly.
They agree to float32 precision.
"""

import logging
import re
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import httpx
import numpy as np
import pandas as pd
from pyproj import CRS, Transformer

from renewable_forecast import paths

logger = logging.getLogger(__name__)

DODS_ROOT = "https://thredds.met.no/thredds/dodsC/meps25epsarchive"

#: The one product that is era-stable across the whole archive window on the 00z run.
#: `meps_lagged_6_h_vc_2_5km` (30 members) stops at the end of 2024 and
#: `meps_det_2_5km` appears only intermittently -- both would put a publication-history
#: boundary inside the training set.
PRODUCT = "meps_det_hl"

#: Wind is stored as grid-relative components, so direction needs the convergence
#: rotation in `wind_speed_direction`. Temperature arrives in kelvin.
VARIABLES = ("x_wind_z", "y_wind_z", "air_temperature_z", "relative_humidity_z")

#: Height levels carried by the `hl` product. These bracket SE3 hub heights, so the
#: power curve can be evaluated by interpolating to the real hub height instead of
#: accepting Open-Meteo's fixed 100 m.
HEIGHTS_M = (80.0, 120.0)

#: Delivery-day interval starts sit at +22..+46 h from the 00z run, so the covered
#: window ends at +47. Six extra steps at the front feed the rolling and lag features
#: without a second request; three at the back feed the forward shifts.
LEAD_FIRST = 16
LEAD_LAST = 50

#: Lambert conformal conic, read from the file's `projection_lambert` attributes.
PROJECTION = {
    "grid_mapping_name": "lambert_conformal_conic",
    "standard_parallel": [63.3, 63.3],
    "longitude_of_central_meridian": 15.0,
    "latitude_of_projection_origin": 63.3,
    "earth_radius": 6371000.0,
}

#: Grid geometry, verified against the published 2-D latitude/longitude arrays for every
#: SE3 cluster point. Holding these as constants means locating a point costs no
#: download at all; `tests/test_meps.py` re-checks them against the live file.
GRID_X0, GRID_DX, GRID_NX = -1060084.0, 2500.0, 949
GRID_Y0, GRID_DY, GRID_NY = -1332517.9, 2500.0, 1069

#: MEPS 00z is disseminated well before 04:00 UTC, comfortably ahead of the 09:00 UTC
#: issue time. The leakage guard in `features/assemble.py` uses the run instant itself,
#: which is the conservative claim: every value is stamped 00z on the issue day.
RUN_HOUR_UTC = 0

#: thredds is a shared public service and its terms ask for no parallel sessions, so
#: the puller is deliberately serial with a pause between requests.
_MIN_INTERVAL_S = 0.5
_MAX_RETRIES = 4
_RETRYABLE = {429, 500, 502, 503, 504}

_SEPARATOR = "-" * 45
_INDEX_LINE = re.compile(r"^\[[0-9]+\]")


def run_url(run: datetime, suffix: str = "") -> str:
    """OPeNDAP URL of the `meps_det_hl` file for one model run."""
    stamp = run.strftime("%Y%m%dT%HZ")
    return f"{DODS_ROOT}/{run:%Y/%m/%d}/{PRODUCT}_{stamp}.ncml{suffix}"


def grid_index(latitude: float, longitude: float) -> tuple[int, int]:
    """Nearest `(y, x)` grid index to a WGS84 point.

    Computed analytically from the projection rather than by searching the published
    coordinate arrays, which would cost a 16 MB download per session.
    """
    transformer = _transformer()
    px, py = transformer.transform(longitude, latitude)
    i = int(np.clip(round((px - GRID_X0) / GRID_DX), 0, GRID_NX - 1))
    j = int(np.clip(round((py - GRID_Y0) / GRID_DY), 0, GRID_NY - 1))
    return j, i


_TRANSFORMER: Transformer | None = None


def _transformer() -> Transformer:
    global _TRANSFORMER  # noqa: PLW0603
    if _TRANSFORMER is None:
        _TRANSFORMER = Transformer.from_crs(
            CRS.from_epsg(4326), CRS.from_cf(PROJECTION), always_xy=True
        )
    return _TRANSFORMER


def grid_convergence(longitude: float) -> float:
    """Angle, in degrees, between grid north and true north at a longitude.

    For a Lambert conformal conic tangent at `standard_parallel`, the cone constant is
    `sin(phi_0)` and convergence is `(lambda - lambda_0) * sin(phi_0)`. Wind *speed* is
    rotation-invariant, but direction is not, so this correction is mandatory before any
    directional feature is derived.
    """
    phi0 = np.radians(PROJECTION["latitude_of_projection_origin"])
    lambda0 = PROJECTION["longitude_of_central_meridian"]
    return float((longitude - lambda0) * np.sin(phi0))


def wind_speed_direction(
    x_wind: np.ndarray, y_wind: np.ndarray, longitude: float
) -> tuple[np.ndarray, np.ndarray]:
    """Convert grid-relative wind components to speed and true-north direction.

    Direction follows the meteorological convention: the compass bearing the wind blows
    *from*.
    """
    speed = np.hypot(x_wind, y_wind)
    grid_direction = (np.degrees(np.arctan2(-x_wind, -y_wind))) % 360
    return speed, (grid_direction + grid_convergence(longitude)) % 360


def _constraint(j: int, i: int) -> str:
    lead = f"{LEAD_FIRST}:1:{LEAD_LAST}"
    height = f"0:1:{len(HEIGHTS_M) - 1}"
    expression = ",".join(
        f"{variable}[{lead}][{height}][{j}:1:{j}][{i}:1:{i}]" for variable in VARIABLES
    )
    # Tomcat rejects unencoded square brackets in a query string with HTTP 400.
    return expression.replace("[", "%5B").replace("]", "%5D")


def parse_ascii(text: str) -> dict[str, np.ndarray]:
    """Decode a DODS ASCII response into arrays keyed by `<variable>.<member>`.

    The ASCII encoding is used in preference to the binary one because the payload is a
    few kilobytes and a text parser has no endianness or padding subtleties to get
    wrong.
    """
    if _SEPARATOR not in text:
        msg = f"unexpected OPeNDAP response: {text[:200]}"
        raise ValueError(msg)
    body = text.split(_SEPARATOR, 1)[1]

    out: dict[str, np.ndarray] = {}
    for block in body.strip().split("\n\n"):
        lines = [line for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        name = lines[0].split("[", 1)[0].strip()
        values: list[float] = []
        for line in lines[1:]:
            payload = line.split(",", 1)[1] if _INDEX_LINE.match(line) else line
            values.extend(float(v) for v in payload.split(",") if v.strip())
        out[name] = np.asarray(values, dtype=float)
    return out


def _frame_for_point(parsed: dict[str, np.ndarray], point) -> pd.DataFrame:
    """Reshape one point's decoded response into tidy rows."""
    n_heights = len(HEIGHTS_M)
    key = f"{VARIABLES[0]}.time"
    if key not in parsed:
        msg = "response carried no time axis"
        raise ValueError(msg)
    valid_time = pd.to_datetime(parsed[key], unit="s", utc=True)

    columns: dict[str, np.ndarray] = {}
    for variable in VARIABLES:
        values = parsed[f"{variable}.{variable}"]
        # _FillValue; anything at this magnitude is missing, not weather.
        values = np.where(values > 1e30, np.nan, values)
        columns[variable] = values.reshape(len(valid_time), n_heights)

    speed, direction = wind_speed_direction(
        columns["x_wind_z"], columns["y_wind_z"], float(point.longitude)
    )
    frames = []
    for h, height in enumerate(HEIGHTS_M):
        frames.append(
            pd.DataFrame(
                {
                    "valid_time": valid_time,
                    "point_id": point.point_id,
                    "height_m": height,
                    "wind_speed": speed[:, h],
                    "wind_direction": direction[:, h],
                    "temperature_c": columns["air_temperature_z"][:, h] - 273.15,
                    "relative_humidity": columns["relative_humidity_z"][:, h],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def fetch_point_ascii(client: httpx.Client, run: datetime, point) -> pd.DataFrame:
    """One point's time series, decoded from the DODS *text* protocol.

    Independent of `fetch_run` in transport, decoding and indexing. Kept as the oracle
    the bounding-box path is checked against rather than as a production route -- it
    costs the server a full domain decompression per point.
    """
    url = run_url(run, ".ascii")
    j, i = grid_index(float(point.latitude), float(point.longitude))
    text = _get(client, f"{url}?{_constraint(j, i)}")
    return _annotate_run(_frame_for_point(parse_ascii(text), point), run)


def _annotate_run(frame: pd.DataFrame, run: datetime) -> pd.DataFrame:
    frame["run_time"] = run
    frame["lead_hour"] = ((frame.valid_time - run).dt.total_seconds() // 3600).astype(
        int
    )
    return frame


#: Half-width, in grid cells, of the neighbourhood averaged around each cluster point.
#: One 2.5 km cell is a noisy stand-in for a cluster of turbines spread over tens of
#: kilometres: the single-cell MEPS power curve correlates 0.936 with SE3 output against
#: 0.959 for the 0.25 degree IFS (`reports/meps_archive.md`). Radius 4 is a 9 x 9 window,
#: ~22 km, about the extent of a cluster. The window's spread is kept as well: it is the
#: deterministic pseudo-ensemble of Molinder et al. (2018).
NEIGHBOURHOOD_RADIUS = 4


def fetch_run(run: datetime, points: pd.DataFrame, radius: int = 0) -> pd.DataFrame:
    """Every point's time series from a single model run.

    One bounding-box request covering all points -- see the module docstring for why
    that is the polite shape as well as the fast one. Raises if the run is absent from
    the archive, so the caller records the gap rather than silently skipping it.

    With `radius > 0` each point's values are the mean over a `(2r+1)^2` window of
    cells, and `wind_speed_nbhd_std` records the spread of speed across it. Wind is
    averaged as components, so a window straddling a direction change is not averaged
    through an angle wrap.
    """
    import xarray as xr

    located = [
        (point, *grid_index(float(point.latitude), float(point.longitude)))
        for point in points.itertuples()
    ]
    j0 = max(min(j for _, j, _ in located) - radius, 0)
    j1 = min(max(j for _, j, _ in located) + radius, GRID_NY - 1)
    i0 = max(min(i for _, _, i in located) - radius, 0)
    i1 = min(max(i for _, _, i in located) + radius, GRID_NX - 1)

    with xr.open_dataset(run_url(run), decode_timedelta=True) as dataset:
        box = (
            dataset[list(VARIABLES)]
            .isel(
                time=slice(LEAD_FIRST, LEAD_LAST + 1),
                y=slice(j0, j1 + 1),
                x=slice(i0, i1 + 1),
            )
            .load()
        )

    valid_time = pd.to_datetime(box.time.values, utc=True)
    lead = ((valid_time - run).total_seconds() // 3600).astype(int)
    if lead[0] != LEAD_FIRST or lead[-1] != LEAD_LAST:
        # The time index is assumed to equal the lead hour, which holds only while the
        # product stays hourly to +66. Fail loudly if that ever changes.
        msg = f"unexpected lead coverage {lead[0]}..{lead[-1]} for run {run}"
        raise ValueError(msg)

    frames = []
    for point, j, i in located:
        window = box.isel(
            y=slice(max(j - radius, j0) - j0, min(j + radius, j1) - j0 + 1),
            x=slice(max(i - radius, i0) - i0, min(i + radius, i1) - i0 + 1),
        )
        # Arrays are (time, height, y, x); a radius of 0 is a 1 x 1 window, so the
        # single-cell path is the same code with nothing to average.
        x_wind = window["x_wind_z"].values
        y_wind = window["y_wind_z"].values
        cell_speed = np.hypot(x_wind, y_wind)
        speed, direction = wind_speed_direction(
            x_wind.mean(axis=(2, 3)), y_wind.mean(axis=(2, 3)), float(point.longitude)
        )
        temperature = window["air_temperature_z"].values.mean(axis=(2, 3)) - 273.15
        humidity = window["relative_humidity_z"].values.mean(axis=(2, 3))
        for h, height in enumerate(HEIGHTS_M):
            frame = pd.DataFrame(
                {
                    "valid_time": valid_time,
                    "point_id": point.point_id,
                    "height_m": height,
                    # Mean of cell speeds, not the speed of the mean vector: the power
                    # curve responds to speed, and vector averaging would shrink it.
                    "wind_speed": cell_speed[:, h].mean(axis=(1, 2))
                    if radius
                    else speed[:, h],
                    "wind_direction": direction[:, h],
                    "temperature_c": temperature[:, h],
                    "relative_humidity": humidity[:, h],
                }
            )
            if radius:
                frame["wind_speed_nbhd_std"] = cell_speed[:, h].std(axis=(1, 2))
            frames.append(frame)
    return _annotate_run(pd.concat(frames, ignore_index=True), run)


def _get(client: httpx.Client, url: str) -> str:
    delay = 10.0
    for attempt in range(1, _MAX_RETRIES + 1):
        response = client.get(url)
        if response.status_code == 200:
            time.sleep(_MIN_INTERVAL_S)
            return response.text
        if response.status_code not in _RETRYABLE or attempt == _MAX_RETRIES:
            response.raise_for_status()
        logger.warning("HTTP %s, retrying in %.0fs", response.status_code, delay)
        time.sleep(delay)
        delay *= 2
    msg = "unreachable"
    raise AssertionError(msg)


def _store(radius: int = 0):
    return paths.PARSED / ("meps" if radius == 0 else f"meps_nbhd{radius}")


def _run_path(run: datetime, radius: int = 0):
    return _store(radius) / f"run={run:%Y%m%dT%H}Z" / "data.parquet"


def runs(start: date, end: date) -> Iterator[datetime]:
    """The 00z run instants over a half-open date range."""
    cursor = start
    while cursor < end:
        yield datetime(cursor.year, cursor.month, cursor.day, RUN_HOUR_UTC, tzinfo=UTC)
        cursor += timedelta(days=1)


def pull(points: pd.DataFrame, start: date, end: date, radius: int = 0) -> int:
    """Backfill every 00z run over a date range, one parquet per run.

    Resumable: a run whose parquet already exists is skipped, so an interrupted pull
    costs nothing to restart. Returns the number of runs newly written.
    """
    written = 0
    missing: list[str] = []
    for run in runs(start, end):
        out = _run_path(run, radius)
        if out.exists():
            continue
        try:
            frame = fetch_run(run, points, radius)
        except (OSError, ValueError) as error:
            # A handful of runs are absent or truncated in the archive; record and move
            # on so one gap cannot abort a multi-hour backfill.
            missing.append(f"{run:%Y-%m-%d}")
            logger.warning("run %s unavailable: %s", run.date(), error)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(out, index=False)
        written += 1
        if written % 25 == 0:
            logger.info("%s runs written, at %s", written, run.date())
        time.sleep(_MIN_INTERVAL_S)
    if missing:
        logger.warning("%s runs unavailable: %s", len(missing), ", ".join(missing))
    return written


def load(
    start: date | None = None, end: date | None = None, radius: int = 0
) -> pd.DataFrame:
    """Read the parsed MEPS store back (single-cell by default)."""
    root = _store(radius)
    files = sorted(root.glob("run=*/data.parquet"))
    if not files:
        return pd.DataFrame()
    if start or end:
        kept = []
        for path in files:
            stamp = (
                datetime.strptime(path.parent.name.removeprefix("run="), "%Y%m%dT%HZ")
                .replace(tzinfo=UTC)
                .date()
            )
            if (start and stamp < start) or (end and stamp >= end):
                continue
            kept.append(path)
        files = kept
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
