"""Backfill ERA5 at every grid cell holding an SE3 onshore turbine.

    uv run python -m grid_signals.forecast.pipelines.pull_era5

Resumable: cells already on disk are skipped. Stops at the end of February 2026 -- the
March-September 2026 holdout stays untouched.
"""

import argparse
import logging

from grid_signals.forecast import paths
from grid_signals.forecast.features import era5_fleet
from grid_signals.forecast.sources import era5, fleet

logger = logging.getLogger(__name__)

START = "2018-01-01"
END = "2026-02-28"


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
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
