"""Backfill the MEPS 00z archive for the SE3 cluster points.

Run-addressed NWP, which removes the whole-day vintage step described in
`reports/openmeteo_vintage.md`. Resumable: runs already on disk are skipped, so this
can be interrupted and restarted freely.

    uv run python -m grid_signals.forecast.pipelines.pull_meps [START] [END]

Defaults cover the backtest window only. The March-September 2026 holdout is
deliberately *not* pulled -- it stays untouched until the single final evaluation.
"""

import argparse
import logging
from datetime import date

from grid_signals.forecast import paths
from grid_signals.forecast.features import sites
from grid_signals.forecast.sources import meps

logger = logging.getLogger(__name__)

#: One day before the first delivery day the design matrix covers, since a delivery day
#: is served by the previous day's 00z run.
DEFAULT_START = date(2024, 2, 15)

#: Exclusive. The last delivery day scored in the backtest is 2026-03-01, served by the
#: 2026-02-28 run. Everything after that is holdout.
DEFAULT_END = date(2026, 3, 1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "start", nargs="?", type=date.fromisoformat, default=DEFAULT_START
    )
    parser.add_argument("end", nargs="?", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--zone", default="SE3")
    parser.add_argument(
        "--newest-first",
        action="store_true",
        help="restore live coverage before older history",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=0,
        help="neighbourhood half-width in cells (0 = single cell)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    # xarray logs every OPeNDAP request at INFO through httpx; far too noisy for a
    # multi-hour backfill.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    paths.ensure_data_dirs()
    points = sites.build(args.zone)
    logger.info(
        "pulling MEPS %s .. %s for %s points", args.start, args.end, len(points)
    )
    written = meps.pull(
        points, args.start, args.end, args.radius, newest_first=args.newest_first
    )
    logger.info("done: %s runs written", written)


if __name__ == "__main__":
    main()
