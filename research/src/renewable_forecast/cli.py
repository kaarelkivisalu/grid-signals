"""Command-line entry point for the research pipelines."""

import argparse
import sys
from datetime import UTC, datetime

from renewable_forecast import config, paths, store, windows

_NOT_YET = {
    "build-dataset": "Phase 4 - feature pipeline",
    "train": "Phase 5 - modelling",
    "backtest": "Phase 3 - protocol and baselines",
    "predict": "Phase 7 - operational dry-run",
}


def _info(args: argparse.Namespace) -> int:
    cfg = config.load(args.experiment)
    issue_day = datetime.now(UTC).date()
    print(f"config:      {cfg.name} ({cfg.fingerprint()})")
    print(f"zone:        {cfg.task.zone}  fuels={cfg.task.fuel_types}")
    print(f"resolution:  {cfg.task.resolution}")
    print(f"issue hour:  {cfg.task.issue_hour_utc:02d}:00 UTC")
    print(f"quantiles:   {len(cfg.task.quantiles)} levels")
    leads = windows.lead_hours(issue_day)
    print(f"delivery:    {windows.delivery_day(issue_day)}")
    print(f"lead hours:  +{min(leads)}..+{max(leads)} ({len(leads)} intervals)")
    print(f"root:        {paths.ROOT}")
    with store.connect() as con:
        views = store.rebuild_views(con)
    print(f"views:       {', '.join(views) if views else '(no parquet data yet)'}")
    return 0


def _todo(args: argparse.Namespace) -> int:
    print(f"`{args.command}` is not implemented yet -- {_NOT_YET[args.command]}.")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to a subcommand."""
    parser = argparse.ArgumentParser(prog="renewable-forecast")
    parser.add_argument("-e", "--experiment", help="name under configs/experiments/")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="show the resolved config and data state")
    for name, phase in _NOT_YET.items():
        sub.add_parser(name, help=f"not implemented -- {phase}")

    args = parser.parse_args(argv)
    return _info(args) if args.command == "info" else _todo(args)


if __name__ == "__main__":
    sys.exit(main())
