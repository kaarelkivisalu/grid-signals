"""Fresh SE3 actuals with immutable raw responses and retrieval identities."""

import hashlib
import os
from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd
from entsoe import EntsoeRawClient, parsers

from grid_signals.forecast import journal, paths, windows
from grid_signals.forecast.sources import entsoe


def refresh(start: date, end: date) -> dict:
    token = os.environ.get("ENTSOE_API_KEY")
    if not token:
        raise ValueError("ENTSOE_API_KEY is not configured")
    client = EntsoeRawClient(api_key=token, retry_count=1, timeout=45)
    now = datetime.now(UTC)
    raw = client.query_generation(
        "SE_3",
        start=pd.Timestamp(start, tz=windows.MARKET_TZ),
        end=pd.Timestamp(end, tz=windows.MARKET_TZ),
    )
    directory = paths.RAW / "entsoe/dataset=actual_generation/zone=SE3"
    directory.mkdir(parents=True, exist_ok=True)
    identity = f"{start:%Y%m%d}_{end:%Y%m%d}_{now:%Y%m%dT%H%M%S}_{uuid4()}"
    xml = directory / f"{identity}.xml"
    xml.write_text(raw, encoding="utf-8")
    long = entsoe._to_long(parsers.parse_generation(raw, nett=True), "value_mw")  # noqa: SLF001 -- shared provider normalization
    if long.empty:
        raise ValueError("actual generation response contains no observations")
    long["zone"], long["fetched_at"] = "SE3", datetime.now(UTC)
    destination = directory / f"{identity}.parquet"
    temporary = destination.with_suffix(".tmp")
    long.to_parquet(temporary, index=False)
    temporary.replace(destination)
    result = {
        "status": "fetched",
        "rows": len(long),
        "received_at": datetime.now(UTC).isoformat(),
        "raw_file": str(xml.relative_to(paths.DATA)),
        "sha256": hashlib.sha256(raw.encode()).hexdigest(),
    }
    journal.record("actual_fetches", result)
    return result
