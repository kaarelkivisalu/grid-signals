"""One installed CLI for forecast operations and focused experiments."""

import argparse
import importlib
import json
import os
import subprocess  # noqa: S404
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from grid_signals.products import PRODUCTS

# Existing experiment functions remain callable by notebooks and the CLI.
PIPELINES = {
    "fetch-actuals": "pull_actuals",
    "fetch-solar": "pull_solar",
    "fetch-meps": "pull_meps",
    "fetch-ifs": "pull_ifs_runs",
    "fetch-era5": "pull_era5",
    "refresh-weather": "refresh_archives",
    "fetch-context": "sources.market_context",
    "train": "train",
    "backtest": "backtest_products",
    "workflow": "daily",
}
EXPERIMENTS = (
    "compare_blocks",
    "compare_calibration",
    "compare_meps",
    "ablate_vintage",
    "decision_study",
    "era5_ceiling",
    "data_audit",
    "price_load",
)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911
    parser = argparse.ArgumentParser(prog="grid-signals", description=__doc__)
    for option in ("data", "output", "config", "reports", "mlruns"):
        parser.add_argument(
            f"--{option}-dir",
            type=Path,
            help=f"Override GRID_SIGNALS_{option.upper()}_DIR",
        )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="Show configured directories and evaluated products")
    ui = sub.add_parser("ui", help="Read saved results in Streamlit")
    ui.add_argument("args", nargs=argparse.REMAINDER)
    for name, module in PIPELINES.items():
        cmd = sub.add_parser(
            name,
            add_help=False,
            help=f"Run {module.replace('_', ' ')}; use --help for options",
        )
        cmd.add_argument("args", nargs=argparse.REMAINDER)
    forecast = sub.add_parser(
        "forecast",
        help="Fit and publish an existing product; saved models follow in 2b",
    )
    forecast.add_argument("--product", choices=PRODUCTS, default="se3-wind")
    forecast.add_argument("--day", type=date.fromisoformat)
    forecast.add_argument("--no-refresh", action="store_true")
    score = sub.add_parser(
        "score", help="Score first eligible publications from saved actuals"
    )
    score.add_argument("--product", choices=PRODUCTS, default="se3-wind")
    export = sub.add_parser(
        "export", help="Export saved results; never train or evaluate holdouts"
    )
    export.add_argument(
        "bundle",
        choices=("explorer", "renewable", "price", "load", "all"),
        default="all",
        nargs="?",
    )
    capture = sub.add_parser("capture", help="Save public comparison forecasts")
    capture.add_argument("--product", choices=PRODUCTS, default="se3-wind")
    capture.add_argument("--day", type=date.fromisoformat, required=True)
    experiment = sub.add_parser(
        "experiment", help="Run a focused development comparison"
    )
    experiment.add_argument("name", choices=EXPERIMENTS)
    experiment.add_argument("args", nargs=argparse.REMAINDER)
    version = sub.add_parser(
        "version", help="Verify code identity or register a new immutable record"
    )
    version.add_argument("--register", type=Path)
    for command in ("fetch-price", "fetch-load"):
        cmd = sub.add_parser(command)
        cmd.add_argument("start", type=date.fromisoformat)
        cmd.add_argument("end", type=date.fromisoformat)
    sub.add_parser(
        "backtest-price", help="Re-run the fixed development price comparison"
    )
    sub.add_parser("backtest-load", help="Re-run the fixed development load comparison")
    args, remainder = parser.parse_known_args(argv)
    if remainder and args.command not in PIPELINES and args.command != "experiment":
        parser.error(f"unrecognized arguments: {' '.join(remainder)}")
    # Modules keep module-level paths, so configure before importing any pipeline.
    for option in ("data", "output", "config", "reports", "mlruns"):
        value = getattr(args, f"{option}_dir")
        if value is not None:
            os.environ[f"GRID_SIGNALS_{option.upper()}_DIR"] = str(value.resolve())
    from dotenv import load_dotenv

    load_dotenv()
    from grid_signals.forecast import paths

    if args.command == "info":
        print(
            json.dumps(
                {
                    "data": str(paths.DATA),
                    "output": str(paths.OUTPUT),
                    "configs": str(paths.CONFIGS),
                    "reports": str(paths.REPORTS),
                    "products": {
                        name: asdict(product) for name, product in PRODUCTS.items()
                    },
                },
                indent=2,
            )
        )
        return 0
    if args.command == "version":
        from grid_signals.forecast import versions

        print(
            json.dumps(
                versions.register(args.register)
                if args.register
                else versions.verify(),
                indent=2,
            )
        )
        return 0
    if args.command == "ui":
        app = Path(__file__).parent / "app/main.py"
        return subprocess.call(  # noqa: S603 -- fixed interpreter, Streamlit receives user CLI options
            [sys.executable, "-m", "streamlit", "run", str(app), *args.args]
        )
    if args.command in PIPELINES:
        module = importlib.import_module(
            ("grid_signals.forecast." + PIPELINES[args.command])
            if args.command == "fetch-context"
            else ("grid_signals.forecast.pipelines." + PIPELINES[args.command])
        )
        return module.main([*remainder, *args.args]) or 0
    if args.command == "experiment":
        module = importlib.import_module("grid_signals.forecast.pipelines." + args.name)
        if hasattr(module, "main"):
            return module.main([*remainder, *args.args]) or 0
        if args.args or remainder:
            parser.error("this experiment accepts no additional arguments")
        print(module.write() if args.name == "decision_study" else module.run())
        return 0
    paths.ensure_data_dirs()
    if args.command == "export":
        modules = {
            "explorer": "export_explorer",
            "renewable": "export_demo",
            "price": "export_price",
            "load": "export_load",
        }
        for name in modules if args.bundle == "all" else [args.bundle]:
            module = importlib.import_module(
                "grid_signals.forecast.reporting." + modules[name]
            )
            print(module.write())
        return 0
    if args.command in {"fetch-price", "fetch-load"}:
        if args.start >= args.end:
            parser.error("start must precede end")
        if args.command == "fetch-price":
            from grid_signals.forecast.sources import prices

            print(prices.refresh(args.start, args.end))
        else:
            from grid_signals.forecast.sources import load

            result = load.pull(args.start, args.end)
            print(json.dumps(result))
            return int(result["failed"] > 0)
        return 0
    if args.command in {"backtest-price", "backtest-load"}:
        module = importlib.import_module(
            "grid_signals.forecast.pipelines." + args.command.removeprefix("backtest-")
        )
        print(module.backtest().to_string(index=False))
        return 0
    product = PRODUCTS[args.product]
    if args.command == "forecast":
        from grid_signals.forecast.operations import forecast

        rows = forecast(args.product, args.day, refresh=not args.no_refresh)
        print(
            json.dumps(
                {
                    "forecast_id": rows.forecast_id.iloc[0],
                    "status": rows.publication_status.iloc[0],
                }
            )
        )
    elif args.command == "score":
        name = {
            "renewable": "score_live",
            "load": "score_load",
            "price": "score_price",
        }[product.adapter]
        module = importlib.import_module("grid_signals.forecast.pipelines." + name)
        print(json.dumps(module.write(), default=str))
    elif args.command == "capture":
        if product.adapter == "price":
            parser.error("no pre-auction public price comparison is defined")
        from grid_signals.forecast.sources import capture

        result = capture.run(
            product.zone,
            "load" if product.adapter == "load" else "wind_solar",
            args.day,
        )
        print(json.dumps(result, default=str))
        return int(result["status"] == "failed")
    return 0
