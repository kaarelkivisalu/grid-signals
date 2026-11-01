"""Pull pinned-model solar weather; all requests retain their issue-age offsets."""

import argparse
import logging
from datetime import UTC, date, datetime

from grid_signals.forecast.features import solar
from grid_signals.forecast.sources import openmeteo


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "start", nargs="?", type=date.fromisoformat, default=date(2024, 3, 6)
    )
    parser.add_argument(
        "end", nargs="?", type=date.fromisoformat, default=datetime.now(UTC).date()
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    openmeteo.pull(
        solar.sites(),
        args.start,
        args.end,
        models=(solar.MODEL,),
        variables=solar.VARIABLES,
        merge=True,
    )


if __name__ == "__main__":
    main()
