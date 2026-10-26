"""Scheduled capture, forecast publication and live scoring, with failure records."""

import argparse
import json
import logging
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv

from renewable_forecast import journal, paths
from renewable_forecast.pipelines import (
    load,
    predict,
    price_forward,
    score_live,
    score_load,
    score_price,
)
from renewable_forecast.reporting import (
    export_demo,
    export_explorer,
    export_load,
    export_price,
)
from renewable_forecast.sources import capture, entsoe, prices
from renewable_forecast.sources import load as observed_load
from renewable_forecast.targets import labels


def capture_public() -> list[dict]:
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    return [
        capture.run(zone, target, tomorrow)
        for zone, target in (
            ("SE3", "wind_solar"),
            ("DE_LU", "wind_solar"),
            ("DE_LU", "load"),
        )
    ]


def forecast(*, refresh: bool = True) -> list[dict]:
    """Independent task failures never suppress the other task or the scorecard."""
    started = datetime.now(UTC)
    outcomes = []
    for zone, fuel in score_live.TASKS:
        entry = {
            "zone": zone,
            "fuel_type": fuel,
            "issue_day": started.date().isoformat(),
            "started_at": datetime.now(UTC).isoformat(),
        }
        try:
            if refresh:
                entsoe.fetch_chunk(
                    entsoe.client(),
                    "actual_generation",
                    zone,
                    started.date() - timedelta(days=7),
                    started.date() + timedelta(days=1),
                )
                if fuel == "wind_onshore":
                    labels.write(zone, fuel)
            rows = predict.run(zone=zone, fuel=fuel, refresh=refresh)
            entry.update(
                status=rows.publication_status.iloc[0],
                forecast_id=rows.forecast_id.iloc[0],
            )
        except Exception as exc:  # noqa: BLE001 -- independent scheduled task boundary
            entry.update(status="failed", error_type=type(exc).__name__)
        entry["finished_at"] = datetime.now(UTC).isoformat()
        journal.record("runs", entry)
        outcomes.append(entry)
    entry = {
        "zone": "DE_LU",
        "fuel_type": "spot_price",
        "issue_day": started.date().isoformat(),
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        if refresh:
            prices.refresh(
                started.date() - timedelta(days=7), started.date() + timedelta(days=2)
            )
        rows = price_forward.publish()
        entry.update(
            status=rows.publication_status.iloc[0], forecast_id=rows.forecast_id.iloc[0]
        )
    except Exception as exc:  # noqa: BLE001 -- preserve independent price failures safely
        entry.update(status="failed", error_type=type(exc).__name__)
    entry["finished_at"] = datetime.now(UTC).isoformat()
    journal.record("runs", entry)
    outcomes.append(entry)
    entry = {
        "zone": "DE_LU",
        "fuel_type": "total_load",
        "issue_day": started.date().isoformat(),
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        if refresh:
            observed_load.fetch(
                started.date() - timedelta(days=7),
                started.date() + timedelta(days=1),
                refresh=True,
            )
        rows = load.publish()
        entry.update(
            status=rows.publication_status.iloc[0], forecast_id=rows.forecast_id.iloc[0]
        )
    except Exception as exc:  # noqa: BLE001 -- independent load publication boundary
        entry.update(status="failed", error_type=type(exc).__name__)
    entry["finished_at"] = datetime.now(UTC).isoformat()
    journal.record("runs", entry)
    outcomes.append(entry)
    publish_artifacts()
    return outcomes


def publish_artifacts() -> list[dict]:
    """Keep existing snapshots available if an independent exporter fails."""
    results = []
    for name, action in (
        ("renewable_scorecard", score_live.write),
        ("price_scorecard", score_price.write),
        ("load_scorecard", score_load.write),
        ("renewable_snapshot", export_demo.write),
        ("price_snapshot", export_price.write),
        ("load_snapshot", export_load.write),
        ("market_explorer", export_explorer.write),
    ):
        try:
            action()
            results.append({"artifact": name, "status": "updated"})
        except Exception as exc:  # noqa: BLE001 -- stale artifact remains available
            result = {
                "artifact": name,
                "status": "failed",
                "error_type": type(exc).__name__,
            }
            journal.record("artifacts", result)
            results.append(result)
    return results


def refresh_actuals() -> list[dict]:
    today = datetime.now(UTC).date()
    outcomes = []
    for zone in dict.fromkeys(zone for zone, _ in score_live.TASKS):
        try:
            entsoe.fetch_chunk(
                entsoe.client(),
                "actual_generation",
                zone,
                today - timedelta(days=7),
                today + timedelta(days=1),
            )
        except Exception as exc:  # noqa: BLE001 -- do not expose request URLs
            outcomes.append(
                {"source": zone, "status": "failed", "error_type": type(exc).__name__}
            )
    try:
        prices.refresh(today - timedelta(days=7), today + timedelta(days=2))
    except Exception as exc:  # noqa: BLE001 -- do not expose request URLs
        outcomes.append(
            {
                "source": "DE_LU_prices",
                "status": "failed",
                "error_type": type(exc).__name__,
            }
        )
    for result in outcomes:
        journal.record("refreshes", result)
    try:
        observed_load.fetch(
            today - timedelta(days=7), today + timedelta(days=1), refresh=True
        )
    except Exception as exc:  # noqa: BLE001 -- do not expose credential-bearing request URLs
        result = {
            "source": "DE_LU_load",
            "status": "failed",
            "error_type": type(exc).__name__,
        }
        journal.record("refreshes", result)
        outcomes.append(result)
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["capture", "forecast", "score"])
    parser.add_argument("--no-refresh", action="store_true")
    args = parser.parse_args()
    load_dotenv(paths.ROOT.parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.mode == "capture":
        result = capture_public()
    elif args.mode == "forecast":
        result = forecast(refresh=not args.no_refresh)
    else:
        result = ([] if args.no_refresh else refresh_actuals()) + publish_artifacts()
    print(json.dumps(result, indent=2))
    return int(any(row["status"] == "failed" for row in result))


if __name__ == "__main__":
    raise SystemExit(main())
