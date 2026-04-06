"""CLI entry point for grid-signals."""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from grid_signals.config import ConfigError
from grid_signals.db.connection import DEFAULT_DB_PATH
from grid_signals.logging_config import configure_logging


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="grid-signals",
        description="Nordic-Baltic Energy Intelligence — data pipeline CLI",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(DEFAULT_DB_PATH),
        help=f"Path to DuckDB file (default: {DEFAULT_DB_PATH})",
    )
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument(
        "--json-log",
        action="store_true",
        default=None,
        help="Force JSON log output",
    )
    log_group.add_argument(
        "--no-json-log",
        action="store_true",
        default=None,
        help="Force human-readable log output",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("daily", help="Run daily ENTSO-E ingestion")
    sub.add_parser("weather", help="Run weather forecast update")

    backfill = sub.add_parser("backfill", help="Backfill a date range")
    backfill.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    backfill.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    backfill.add_argument(
        "--gaps-only",
        action="store_true",
        default=False,
        help="Only backfill missing data (detect gaps first, then fetch only what is needed)",
    )

    validate_cmd = sub.add_parser("validate", help="Run data validation checks")
    validate_cmd.add_argument(
        "--start", default=None, help="Start date (YYYY-MM-DD, default: yesterday)"
    )
    validate_cmd.add_argument(
        "--end",
        default=None,
        help="End date exclusive (YYYY-MM-DD, default: start + 1 day)",
    )
    sub.add_parser("ui", help="Launch the Streamlit web interface")

    health_cmd = sub.add_parser("health", help="Check data freshness across all tables")
    health_cmd.add_argument(
        "--max-age",
        type=int,
        default=26,
        help="Maximum acceptable age in hours (default: 26)",
    )

    backup_cmd = sub.add_parser("backup", help="Backup DuckDB to S3")
    backup_cmd.add_argument("--bucket", required=True, help="S3 bucket name")
    backup_cmd.add_argument(
        "--prefix",
        default="grid-signals/backups",
        help="S3 key prefix (default: grid-signals/backups)",
    )

    agent_cmd = sub.add_parser(
        "agent", help="Ask the energy intelligence agent a question"
    )
    agent_cmd.add_argument("question", help="Question to ask the agent")
    agent_cmd.add_argument(
        "--model",
        default="claude-haiku-4-5",
        help="Claude model to use (default: claude-haiku-4-5)",
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
        "--no-save",
        action="store_true",
        default=False,
        help="Do not save the briefing to a file",
    )
    briefing_cmd.add_argument(
        "--model",
        default="claude-haiku-4-5",
        help="Claude model to use (default: claude-haiku-4-5)",
    )
    briefing_cmd.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Maximum agent turns (default: 15)",
    )

    # -- query subcommands (direct tool access) --
    query_cmd = sub.add_parser(
        "query", help="Query data directly (same tools the agent uses)"
    )
    query_sub = query_cmd.add_subparsers(dest="query_command", required=True)

    # prices
    q_prices = query_sub.add_parser("prices", help="Day-ahead electricity prices")
    q_prices.add_argument(
        "zone", help="Bidding zone (EE, LV, LT, FI, SE1-SE4, NO1-NO5, DK1, DK2)"
    )
    q_prices.add_argument("start_date", help="Start date (YYYY-MM-DD), inclusive")
    q_prices.add_argument("end_date", help="End date (YYYY-MM-DD), exclusive")

    # generation
    q_gen = query_sub.add_parser("generation", help="Generation mix by fuel type")
    q_gen.add_argument(
        "zone", help="Bidding zone (EE, LV, LT, FI, SE1-SE4, NO1-NO5, DK1, DK2)"
    )
    q_gen.add_argument("start_date", help="Start date (YYYY-MM-DD), inclusive")
    q_gen.add_argument("end_date", help="End date (YYYY-MM-DD), exclusive")
    q_gen.add_argument("--fuel-type", default=None, help="Filter by fuel type")

    # weather
    q_weather = query_sub.add_parser("weather", help="Weather forecast summary")
    q_weather.add_argument(
        "location", help="Location name (e.g. EE_tallinn, SE4_skane, FI_inland)"
    )
    q_weather.add_argument("start_date", help="Start date (YYYY-MM-DD), inclusive")
    q_weather.add_argument("end_date", help="End date (YYYY-MM-DD), exclusive")

    # outages
    q_outages = query_sub.add_parser("outages", help="REMIT outage messages")
    q_outages.add_argument(
        "zone", help="Bidding zone (EE, LV, LT, FI, SE1-SE4, NO1-NO5, DK1, DK2)"
    )
    q_outages.add_argument("--fuel-type", default=None, help="Filter by fuel type")
    q_outages.add_argument(
        "--active-at",
        default=None,
        help="Find outages active at this time (YYYY-MM-DD or ISO datetime)",
    )

    # flows
    q_flows = query_sub.add_parser("flows", help="Cross-border power flows")
    q_flows.add_argument("from_zone", help="Exporting zone")
    q_flows.add_argument("to_zone", help="Importing zone")
    q_flows.add_argument("start_date", help="Start date (YYYY-MM-DD), inclusive")
    q_flows.add_argument("end_date", help="End date (YYYY-MM-DD), exclusive")

    # load
    q_load = query_sub.add_parser("load", help="Load forecast summary")
    q_load.add_argument(
        "zone", help="Bidding zone (EE, LV, LT, FI, SE1-SE4, NO1-NO5, DK1, DK2)"
    )
    q_load.add_argument("start_date", help="Start date (YYYY-MM-DD), inclusive")
    q_load.add_argument("end_date", help="End date (YYYY-MM-DD), exclusive")

    # spread
    q_spread = query_sub.add_parser("spread", help="Price spread between two zones")
    q_spread.add_argument("zone_1", help="First zone (spread = zone_1 - zone_2)")
    q_spread.add_argument("zone_2", help="Second zone")
    q_spread.add_argument("start_date", help="Start date (YYYY-MM-DD), inclusive")
    q_spread.add_argument("end_date", help="End date (YYYY-MM-DD), exclusive")

    # similar-days
    q_similar = query_sub.add_parser(
        "similar-days",
        help="Find historical days with similar weather and their prices",
    )
    q_similar.add_argument("zone", help="Bidding zone for price data")
    q_similar.add_argument("location", help="Weather location name")
    q_similar.add_argument(
        "--wind", type=float, required=True, help="Target wind speed (m/s)"
    )
    q_similar.add_argument(
        "--temp", type=float, required=True, help="Target temperature (°C)"
    )
    q_similar.add_argument(
        "--wind-tolerance",
        type=float,
        default=2.0,
        help="Wind tolerance (m/s, default: 2.0)",
    )
    q_similar.add_argument(
        "--temp-tolerance",
        type=float,
        default=3.0,
        help="Temp tolerance (°C, default: 3.0)",
    )
    q_similar.add_argument(
        "--limit", type=int, default=10, help="Max results (default: 10)"
    )

    return parser.parse_args(argv)


def _build_tool_input(args: argparse.Namespace) -> tuple[str, dict]:  # noqa: PLR0911
    """Map parsed query subcommand args to (tool_name, tool_input) pair."""
    cmd = args.query_command
    if cmd == "prices":
        return "get_day_ahead_prices", {
            "zone": args.zone,
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
    if cmd == "generation":
        inp: dict = {
            "zone": args.zone,
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
        if args.fuel_type:
            inp["fuel_type"] = args.fuel_type
        return "get_generation_mix", inp
    if cmd == "weather":
        return "get_wind_forecast", {
            "location": args.location,
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
    if cmd == "outages":
        inp = {"zone": args.zone}
        if args.fuel_type:
            inp["fuel_type"] = args.fuel_type
        if args.active_at:
            inp["active_at"] = args.active_at
        return "get_outages", inp
    if cmd == "flows":
        return "get_cross_border_flows", {
            "from_zone": args.from_zone,
            "to_zone": args.to_zone,
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
    if cmd == "load":
        return "get_load_forecast", {
            "zone": args.zone,
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
    if cmd == "spread":
        return "calculate_spread", {
            "zone_1": args.zone_1,
            "zone_2": args.zone_2,
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
    if cmd == "similar-days":
        return "get_historical_similar_days", {
            "zone": args.zone,
            "location": args.location,
            "target_wind_ms": args.wind,
            "target_temp_c": args.temp,
            "wind_tolerance_ms": args.wind_tolerance,
            "temp_tolerance_c": args.temp_tolerance,
            "limit": args.limit,
        }
    msg = f"Unknown query command: {cmd!r}"
    raise ValueError(msg)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    json_log: bool | None = None
    if args.json_log:
        json_log = True
    elif args.no_json_log:
        json_log = False
    configure_logging(json_output=json_log)

    db_path = Path(args.db)

    try:
        return _run_command(args, db_path)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1


def _run_command(args: argparse.Namespace, db_path: Path) -> int:
    if args.command == "daily":
        from grid_signals.pipeline import run_daily

        run_daily(db_path)

    elif args.command == "weather":
        from grid_signals.pipeline import run_weather

        run_weather(db_path)

    elif args.command == "backfill":
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC)
        if args.gaps_only:
            from grid_signals.pipeline import run_backfill_gaps

            run_backfill_gaps(db_path, start, end)
        else:
            from grid_signals.pipeline import run_backfill

            run_backfill(db_path, start, end)

    elif args.command == "validate":
        from grid_signals.db.connection import get_connection
        from grid_signals.db.schema import create_tables
        from grid_signals.validation import run_all_validations

        v_start = None
        v_end = None
        if args.start:
            v_start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
        if args.end:
            v_end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC)

        con = get_connection(db_path)
        try:
            create_tables(con)
            run_all_validations(con, start=v_start, end=v_end)
        finally:
            con.close()

    elif args.command == "ui":
        import subprocess  # noqa: S404

        app_path = Path(__file__).parent / "app" / "main.py"
        subprocess.run(  # noqa: S603
            ["streamlit", "run", str(app_path)],
            check=True,
        )

    elif args.command == "agent":
        from grid_signals.agent import run_agent
        from grid_signals.db.connection import get_connection
        from grid_signals.db.schema import create_tables

        con = get_connection(db_path)
        try:
            create_tables(con)
            agent_kwargs: dict = {"model": args.model}
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

    elif args.command == "query":
        import json

        from grid_signals.agent.tools import execute_tool
        from grid_signals.db.connection import get_connection

        con = get_connection(db_path, read_only=True)
        try:
            tool_name, tool_input = _build_tool_input(args)
            result_json = execute_tool(tool_name, tool_input, con)
            print(json.dumps(json.loads(result_json), indent=2))
        finally:
            con.close()

    elif args.command == "briefing":
        from grid_signals.briefing import DEFAULT_OUTPUT_DIR, generate_briefing
        from grid_signals.db.connection import get_connection
        from grid_signals.db.schema import create_tables

        target_date = None
        if args.date:
            target_date = (
                datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=UTC).date()
            )

        if args.no_save:
            output_dir = None
        elif args.output:
            output_dir = Path(args.output)
        else:
            output_dir = DEFAULT_OUTPUT_DIR

        con = get_connection(db_path)
        try:
            create_tables(con)
            kwargs = {
                "target_date": target_date,
                "output_dir": output_dir,
                "model": args.model,
            }
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

    elif args.command == "health":
        from grid_signals.db.connection import get_connection
        from grid_signals.db.schema import create_tables
        from grid_signals.health import check_data_freshness

        con = get_connection(db_path, read_only=True)
        try:
            create_tables(con)
            status = check_data_freshness(con, max_age_hours=args.max_age)
            if not status.healthy:
                print("UNHEALTHY: some tables have stale data", file=sys.stderr)
                return 1
            print("HEALTHY: all tables within freshness threshold")
        finally:
            con.close()

    elif args.command == "backup":
        from grid_signals.backup import backup_database

        uri = backup_database(db_path, s3_bucket=args.bucket, prefix=args.prefix)
        print(f"Backup uploaded: {uri}")

    return 0
