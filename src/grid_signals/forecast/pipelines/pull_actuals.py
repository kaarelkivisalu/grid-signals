"""Refresh recent SE3 wind / DE-LU solar observations before production fitting."""

import argparse
import logging
from datetime import UTC, date, datetime, timedelta

from dotenv import load_dotenv

from grid_signals.forecast import paths
from grid_signals.forecast.sources import entsoe
from grid_signals.forecast.targets import labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "start",
        nargs="?",
        type=date.fromisoformat,
        default=datetime.now(UTC).date() - timedelta(days=7),
    )
    parser.add_argument(
        "end",
        nargs="?",
        type=date.fromisoformat,
        default=datetime.now(UTC).date() + timedelta(days=1),
    )
    args = parser.parse_args(argv)
    if args.start >= args.end:
        parser.error("start must precede end")
    load_dotenv(paths.ROOT.parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    tally = entsoe.backfill(
        ["actual_generation"],
        args.start,
        args.end,
        zones={"actual_generation": ["SE3", "DE_LU"]},
        workers=1,
    )
    if tally["failed"]:
        raise RuntimeError(f"actuals refresh incomplete: {tally}")
    labels.write()
    logging.getLogger(__name__).info("actuals refresh: %s", tally)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
