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

    agent_cmd = sub.add_parser("agent", help="Ask the energy intelligence agent a question")
    agent_cmd.add_argument("question", help="Question to ask the agent")
    agent_cmd.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Claude model to use (default: claude-haiku-4-5-20251001)",
    )
    agent_cmd.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Maximum agent turns (default: 15)",
    )

    briefing_cmd = sub.add_parser("briefing", help="Generate a daily morning briefing")
    briefing_cmd.add_argument(
        "--date",
        default=None,
        help="Date to generate briefing for (YYYY-MM-DD, default: today)",
    )
    briefing_cmd.add_argument(
        "--output",
        default=None,
        help="Output directory for Markdown file (default: briefings/)",
    )
    briefing_cmd.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Claude model to use (default: claude-haiku-4-5-20251001)",
    )
    briefing_cmd.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Maximum agent turns (default: 15)",
    )

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

    elif args.command == "agent":
        from grid_signals.agent import run_agent
        from grid_signals.db.connection import get_connection
        from grid_signals.db.schema import create_tables

        con = get_connection(db_path)
        try:
            create_tables(con)
            agent_kwargs: dict = dict(model=args.model)
            if args.max_turns is not None:
                agent_kwargs["max_turns"] = args.max_turns
            result = run_agent(args.question, con, **agent_kwargs)
            print(result.content)
            logger = logging.getLogger(__name__)
            logger.info(
                "tokens: %d in / %d out, tool calls: %d, cost: $%.4f",
                result.input_tokens,
                result.output_tokens,
                len(result.tool_calls),
                result.estimated_cost_usd,
            )
        finally:
            con.close()

    elif args.command == "briefing":
        from grid_signals.briefing import DEFAULT_OUTPUT_DIR, generate_briefing
        from grid_signals.db.connection import get_connection
        from grid_signals.db.schema import create_tables

        target_date = None
        if args.date:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

        output_dir = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR

        con = get_connection(db_path)
        try:
            create_tables(con)
            kwargs = dict(
                target_date=target_date,
                output_dir=output_dir,
                model=args.model,
            )
            if args.max_turns is not None:
                kwargs["max_turns"] = args.max_turns
            result = generate_briefing(con, **kwargs)
            print(result.content)
            logger = logging.getLogger(__name__)
            if result.output_path:
                logger.info("Briefing saved to %s", result.output_path)
            logger.info(
                "tokens: %d in / %d out, tool calls: %d, cost: $%.4f",
                result.agent_result.input_tokens,
                result.agent_result.output_tokens,
                len(result.agent_result.tool_calls),
                result.agent_result.estimated_cost_usd,
            )
        finally:
            con.close()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.getLogger(__name__).exception("pipeline failed")
        sys.exit(1)
