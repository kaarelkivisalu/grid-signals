"""Backfill ERA5 at every grid cell holding an SE3 onshore turbine.

    uv run python -m renewable_forecast.pipelines.pull_era5

Resumable: cells already on disk are skipped. Stops at the end of February 2026 -- the
March-September 2026 holdout stays untouched.
"""

import logging

from renewable_forecast import paths
from renewable_forecast.features import era5_fleet
from renewable_forecast.sources import era5, fleet

logger = logging.getLogger(__name__)

START = "2018-01-01"
END = "2026-02-28"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("ecmwf.datastores").setLevel(logging.WARNING)
    paths.ensure_data_dirs()
    turbines = era5_fleet.turbine_table(fleet.load_turbines())
    cells = era5.cells_for(turbines.latitude, turbines.longitude)
    files = era5.pull(cells, START, END)
    logger.info("done: %s cells", len(files))


if __name__ == "__main__":
    main()
