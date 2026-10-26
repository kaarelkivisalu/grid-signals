"""Bounded public observations for additional demo areas, independent of modelling.

Never used as model inputs or matched pre-auction forecasts. Each file retains its
retrieval timestamp; failures report exception classes without credential URLs.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from renewable_forecast import paths
from renewable_forecast.sources.entsoe import client

ZONES = {
    "FI": "FI",
    "EE": "EE",
    "FR": "FR",
    "NL": "NL",
    "DK1": "DK_1",
    "DK2": "DK_2",
    "SE1": "SE_1",
    "SE2": "SE_2",
    "SE4": "SE_4",
}


def normalise_generation(raw: pd.DataFrame) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs("Actual Aggregated", axis=1, level=1)
    result = pd.DataFrame(index=raw.index)
    for label, column in [
        ("Solar", "solar"),
        ("Wind Onshore", "wind_onshore"),
        ("Wind Offshore", "wind_offshore"),
    ]:
        if label in raw:
            result[column] = raw[label]
    return result


def fetch(
    zone: str, kind: str, start: date, end: date, output: Path, *, refresh: bool = False
) -> dict:
    destination = output / f"{zone}_{kind}.parquet"
    if destination.exists() and not refresh:
        return {"zone": zone, "kind": kind, "status": "cached"}
    cli = client()
    cli.timeout = 30
    first, stop = (pd.Timestamp(value, tz="Europe/Brussels") for value in [start, end])
    try:
        if kind == "price":
            result = cli.query_day_ahead_prices(
                ZONES[zone], start=first, end=stop
            ).to_frame("price")
        elif kind == "load":
            raw = cli.query_load(ZONES[zone], start=first, end=stop)
            result = (
                raw.to_frame("load")
                if isinstance(raw, pd.Series)
                else raw.rename(columns={"Actual Load": "load"})[["load"]]
            )
        else:
            result = normalise_generation(
                cli.query_generation(ZONES[zone], start=first, end=stop)
            )
        result.index = pd.to_datetime(result.index, utc=True)
        result = result[(result.index >= first) & (result.index < stop)]
        result.index.name = "valid_time"
        result["fetched_at"] = pd.Timestamp(datetime.now(UTC))
        output.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp.parquet")
        result.to_parquet(temporary)
        temporary.replace(destination)
        return {
            "zone": zone,
            "kind": kind,
            "status": "fetched",
            "intervals": len(result),
        }
    except Exception as exc:  # noqa: BLE001 -- API URLs can contain credentials
        return {
            "zone": zone,
            "kind": kind,
            "status": "failed",
            "error_type": type(exc).__name__,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 16))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if not 0 < (args.end - args.start).days <= 90:
        parser.error("choose a nonempty range of at most 90 days")
    load_dotenv(paths.ROOT.parent / ".env")
    jobs = [
        (zone, kind)
        for zone in ZONES
        for kind in ["price", "load", "generation"]
        if kind != "generation" or zone not in {"SE1", "SE2", "SE4"}
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(
                fetch,
                zone,
                kind,
                args.start,
                args.end,
                paths.DATA / "market_context",
                refresh=args.refresh,
            )
            for zone, kind in jobs
        ]
        for future in futures:
            print(json.dumps(future.result()), flush=True)
