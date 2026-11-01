"""DE-LU actual total load: preserve reported quarter-hours and retrieval evidence."""

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from entsoe.exceptions import NoMatchingDataError

from grid_signals.forecast import paths, windows
from grid_signals.forecast.sources import entsoe

ROOT = paths.RAW / "entsoe/dataset=actual_load/zone=DE_LU"
logger = logging.getLogger(__name__)


def fetch(start: date, stop: date, *, refresh: bool = False) -> str:
    destination = ROOT / f"{start:%Y%m%d}_{stop:%Y%m%d}.parquet"
    if destination.exists() and not refresh:
        return "cached"
    first, last = (pd.Timestamp(day, tz=windows.MARKET_TZ) for day in [start, stop])
    try:
        raw = entsoe.client().query_load("DE_LU", start=first, end=last)
    except NoMatchingDataError:
        return "missing"
    if isinstance(raw, pd.DataFrame):
        if list(raw.columns) != ["Actual Load"]:
            raise ValueError(f"unexpected actual-load columns: {list(raw.columns)}")
        raw = raw["Actual Load"]
    rows = raw.rename("mw").rename_axis("valid_time").reset_index()
    rows["valid_time"] = pd.to_datetime(rows.valid_time, utc=True)
    rows = rows[(rows.valid_time >= first) & (rows.valid_time < last)].copy()
    rows["fetched_at"] = datetime.now(UTC)
    rows["zone"] = "DE_LU"
    rows["target"] = "actual_total_load"
    rows["unit"] = "MW"
    if rows.empty:
        return "missing"
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.parquet")
    rows.to_parquet(temporary, index=False)
    temporary.replace(destination)
    return "fetched"


def pull(start: date, stop: date) -> dict:
    def run(bounds) -> str:
        try:
            result = fetch(*bounds)
        except Exception as exc:  # noqa: BLE001 -- request errors can contain credentials
            logger.error("load %s to %s failed (%s)", *bounds, type(exc).__name__)  # noqa: TRY400 -- tracebacks can expose API keys
            return "failed"
        logger.info("load %s to %s: %s", *bounds, result)
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, entsoe.chunks(start, stop)))
    return {
        name: results.count(name) for name in ["cached", "fetched", "missing", "failed"]
    }


def load() -> pd.Series:
    files = sorted(ROOT.glob("*.parquet"))
    if not files:
        raise RuntimeError("No DE-LU load observations cached; run sources.load")
    raw = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    raw = raw.sort_values("fetched_at").drop_duplicates("valid_time", keep="last")
    series = raw.set_index("valid_time").mw.sort_index()
    return series.where(series > 0).rename("load")


def native(series: pd.Series) -> pd.Series:
    """Require four genuine reported values per UTC hour; never forward-fill targets."""
    count = series.notna().groupby(series.index.floor("h")).transform("sum")
    return series[(count == 4) & (series.index.minute % 15 == 0)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2024, 3, 1))
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=datetime.now(UTC).date() + timedelta(days=1),
    )
    args = parser.parse_args()
    load_dotenv(paths.ROOT.parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    summary = pull(args.start, args.end)
    print(json.dumps(summary))
    raise SystemExit(int(summary["failed"] > 0))
