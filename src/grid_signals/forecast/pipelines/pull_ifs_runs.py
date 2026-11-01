"""Backfill ECMWF IFS HRES 00z runs for the SE3 cluster points.

    uv run python -m grid_signals.forecast.pipelines.pull_ifs_runs [START] [END]

Defaults cover the backtest window only, like `pull_meps`. The holdout is not pulled.
"""

import argparse
import logging
from datetime import date

from grid_signals.forecast import paths
from grid_signals.forecast.features import sites
from grid_signals.forecast.pipelines.pull_meps import DEFAULT_END
from grid_signals.forecast.sources import ifs_runs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "start", nargs="?", type=date.fromisoformat, default=ifs_runs.ARCHIVE_START
    )
    parser.add_argument("end", nargs="?", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--zone", default="SE3")
    parser.add_argument("--run-hour", type=int, default=ifs_runs.RUN_HOUR_UTC)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    paths.ensure_data_dirs()
    written = ifs_runs.pull(sites.build(args.zone), args.start, args.end, args.run_hour)
    logging.getLogger(__name__).info("done: %s runs written", written)


if __name__ == "__main__":
    main()
