"""ERA5 hourly reanalysis at every grid cell the SE3 fleet occupies, from the CDS.

ERA5 is the closest thing to *what the weather actually was*, so a model fitted on it
sets a ceiling on how well generation can be explained from weather at all -- see
`pipelines/era5_ceiling.py`. Derived fields are built in `features/era5_fleet.py`.

Every occupied 0.25 degree cell is pulled, not the eight cluster centroids: each turbine
then reads its own cell, which removes cluster aggregation as a possible explanation for
a miss.

**Why the timeseries dataset, not the gridded one.** `reanalysis-era5-single-levels`
over the SE3 box costs ~370k units a year against a 121k per-request limit, and the CDS
rejects outright any request beyond a small per-dataset queue -- 31 of 35 quarterly
requests were rejected on the first attempt, and each accepted one took ~13 minutes.
`reanalysis-era5-single-levels-timeseries` is served from the cloud-optimised ARCO copy
of the same data: one request returns one cell for the whole period in ~30 s.

Requests go through `ecmwf-datastores-client`, the designated successor to `cdsapi`.
"""

import hashlib
import json
import logging
import os
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from dotenv import load_dotenv

from renewable_forecast import paths

logger = logging.getLogger(__name__)

DATASET = "reanalysis-era5-single-levels-timeseries"
GRID_STEP = 0.25

VARIABLES = (
    "100m_u_component_of_wind",
    "100m_v_component_of_wind",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "2m_temperature",
    "2m_dewpoint_temperature",
    "surface_pressure",
    "boundary_layer_height",
)

#: The CDS rejects, rather than queues, requests beyond a small number in flight.
MAX_IN_FLIGHT = 4
_POLL_S = 5.0


def client():
    """A datastores client built from the repository `.env`, not `~/.ecmwfdatastoresrc`."""
    from ecmwf.datastores import Client

    load_dotenv(paths.ROOT.parent / ".env")
    return Client(
        url=os.environ["ECMWF_DATASTORES_URL"],
        key=os.environ["ECMWF_DATASTORES_KEY"],
        progress=False,
    )


def snap(values: np.ndarray) -> np.ndarray:
    """Round coordinates onto the ERA5 0.25 degree grid."""
    return np.round(np.asarray(values) / GRID_STEP) * GRID_STEP


def cells_for(latitude: np.ndarray, longitude: np.ndarray) -> pd.DataFrame:
    """The distinct grid cells a set of locations falls in."""
    cells = pd.DataFrame({"latitude": snap(latitude), "longitude": snap(longitude)})
    return (
        cells.drop_duplicates()
        .sort_values(["latitude", "longitude"])
        .reset_index(drop=True)
    )


def request(latitude: float, longitude: float, start: str, end: str) -> dict:
    return {
        "variable": list(VARIABLES),
        "location": {"latitude": float(latitude), "longitude": float(longitude)},
        "date": [f"{start}/{end}"],
        "data_format": "netcdf",
    }


def _raw_path(params: dict) -> Path:
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    return paths.RAW / "era5" / f"{digest[:20]}.zip"


def pull(cells: pd.DataFrame, start: str, end: str) -> list[Path]:
    """Fetch every cell, keeping at most `MAX_IN_FLIGHT` requests on the server.

    Resumable: cells already on disk are skipped. A rejected request goes back on the
    queue rather than failing the pull, since rejection only means "too many in flight".
    """
    cds = client()
    todo = [
        request(row.latitude, row.longitude, start, end) for row in cells.itertuples()
    ]
    todo = [p for p in todo if not _raw_path(p).exists()]
    logger.info("%s of %s cells to fetch", len(todo), len(cells))
    active: list[tuple[dict, object]] = []
    done = len(cells) - len(todo)

    while todo or active:
        while todo and len(active) < MAX_IN_FLIGHT:
            params = todo.pop(0)
            active.append((params, cds.submit(DATASET, params)))
        time.sleep(_POLL_S)
        still = []
        for params, remote in active:
            status = remote.status
            if status == "successful":
                path = _raw_path(params)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")
                remote.download(str(tmp))
                tmp.rename(path)
                done += 1
                logger.info("%s/%s %s", done, len(cells), params["location"])
            elif status in {"rejected", "failed", "dismissed", "deleted"}:
                logger.warning("%s %s, requeueing", params["location"], status)
                todo.append(params)
            else:
                still.append((params, remote))
        active = still
    return [
        _raw_path(request(r.latitude, r.longitude, start, end))
        for r in cells.itertuples()
    ]


def _open(path: Path) -> xr.Dataset:
    """One downloaded cell. The CDS zips a netCDF per stream; read them from memory."""
    import netCDF4

    with zipfile.ZipFile(path) as archive:
        parts = []
        for name in archive.namelist():
            handle = netCDF4.Dataset("inmemory.nc", memory=archive.read(name))
            parts.append(xr.open_dataset(xr.backends.NetCDF4DataStore(handle)).load())
    return xr.merge(parts, compat="override")


def load_cells(files: list[Path] | None = None) -> xr.Dataset:
    """Every downloaded cell stacked along a `cell` dimension, sorted in time.

    `latitude` and `longitude` become per-cell coordinates, snapped onto the grid.
    """
    files = files or sorted((paths.RAW / "era5").glob("*.zip"))
    datasets = []
    for path in files:
        cell = _open(path)
        lat = float(snap(cell.latitude.values))
        lon = float(snap(cell.longitude.values))
        cell = cell.drop_vars(["latitude", "longitude"], errors="ignore")
        datasets.append(
            cell.expand_dims(cell=1).assign_coords(
                latitude=("cell", [lat]), longitude=("cell", [lon])
            )
        )
    grid = xr.concat(datasets, dim="cell").sortby("valid_time")
    return grid.drop_vars(["number", "expver"], errors="ignore")
