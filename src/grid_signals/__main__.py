"""CLI entry point: python -m grid_signals <command>."""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from grid_signals.db.connection import DEFAULT_DB_PATH


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="grid_signals",
        description="Nordic-Baltic Energy Intelligence — data pipeline CLI",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(DEFAULT_DB_PATH),
        help=f"Path to DuckDB file (default: {DEFAULT_DB_PATH})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("daily", help="Run daily ENTSO-E ingestion")
    sub.add_parser("weather", help="Run weather forecast update")

    backfill = sub.add_parser("backfill", help="Backfill a date range")
    backfill.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    backfill.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")

    sub.add_parser("validate", help="Run data validation checks")

    return parser.parse_args(argv)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging()

    db_path = Path(args.db)

    if args.command == "daily":
        from grid_signals.pipeline import run_daily

        run_daily(db_path)

    elif args.command == "weather":
        from grid_signals.pipeline import run_weather

        run_weather(db_path)

    elif args.command == "backfill":
        from grid_signals.pipeline import run_backfill

        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC)
        run_backfill(db_path, start, end)

    elif args.command == "validate":
        from grid_signals.db.connection import get_connection
        from grid_signals.db.schema import create_tables
        from grid_signals.validation import run_all_validations

        con = get_connection(db_path)
        try:
            create_tables(con)
            run_all_validations(con)
        finally:
            con.close()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.getLogger(__name__).exception("pipeline failed")
        sys.exit(1)
