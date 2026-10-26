"""Capture public forecasts as received, preserving raw XML and retrieval times."""

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree  # noqa: S405 -- XML from the configured ENTSO-E API

import pandas as pd
from entsoe import EntsoeRawClient, parsers
from entsoe.exceptions import NoMatchingDataError

from renewable_forecast import journal, windows
from renewable_forecast.sources import entsoe


def document_metadata(xml: str) -> dict:
    root = ElementTree.fromstring(xml)  # noqa: S314 -- trusted ENTSO-E response
    fields = {}
    for element in root:
        name = element.tag.rsplit("}", 1)[-1]
        if name in {
            "mRID",
            "revisionNumber",
            "createdDateTime",
            "type",
            "process.processType",
        }:
            fields[name] = element.text
    return fields


def run(zone: str, target: str, delivery: date, root: Path = journal.ROOT) -> dict:
    cutoff = windows.issue_time(delivery - timedelta(days=1))
    started = datetime.now(UTC)
    capture_id = str(uuid4())
    directory = root / "raw_captures"
    directory.mkdir(parents=True, exist_ok=True)
    metadata = {
        "capture_id": capture_id,
        "zone": zone,
        "target": target,
        "delivery_day": delivery.isoformat(),
        "information_cutoff_at": cutoff.isoformat(),
        "requested_at": started.isoformat(),
        "source": "entsoe",
        "process_type": "A18" if target == "wind_solar" else "A01",
    }
    token = os.environ.get("ENTSOE_API_KEY")
    if target not in {"wind_solar", "load"}:
        raise ValueError("target must be wind_solar or load")
    if not token:
        metadata.update(
            status="failed",
            error_type="MissingCredentials",
            received_at=datetime.now(UTC).isoformat(),
            eligible_at_cutoff=False,
        )
        journal.record("captures", metadata, root)
        return metadata
    try:
        client = EntsoeRawClient(api_key=token, retry_count=1, timeout=45)
        start = pd.Timestamp(delivery, tz=windows.MARKET_TZ)
        stop = start + pd.DateOffset(days=1)
        if target == "wind_solar":
            xml = client.query_wind_and_solar_forecast(
                entsoe.ZONE_TO_ENTSOE[zone], start=start, end=stop, process_type="A18"
            )
            parsed = parsers.parse_generation(xml, nett=True)
        elif target == "load":
            xml = client.query_load_forecast(
                entsoe.ZONE_TO_ENTSOE[zone], start=start, end=stop
            )
            parsed = parsers.parse_loads(xml, process_type="A01")
        received = datetime.now(UTC)
        raw_path = directory / f"{capture_id}.xml"
        raw_path.write_text(xml, encoding="utf-8")
        rows = entsoe._to_long(parsed, "forecast_mw")  # noqa: SLF001
        rows["period_start"] = pd.to_datetime(rows.period_start, utc=True)
        rows = rows[(rows.period_start >= start) & (rows.period_start < stop)]
        rows.to_parquet(directory / f"{capture_id}.parquet", index=False)
        metadata.update(
            received_at=received.isoformat(),
            eligible_at_cutoff=received <= cutoff,
            status="captured" if not rows.empty else "missing",
            sha256=hashlib.sha256(xml.encode()).hexdigest(),
            document=document_metadata(xml),
            rows=len(rows),
        )
    except NoMatchingDataError:
        metadata.update(
            status="missing",
            received_at=datetime.now(UTC).isoformat(),
            eligible_at_cutoff=False,
        )
    except Exception as exc:  # noqa: BLE001 -- capture boundary; preserve failures without credential-bearing messages
        # Never persist request exception text: the HTTP URL can contain the API key.
        metadata.update(
            status="failed",
            error_type=type(exc).__name__,
            received_at=datetime.now(UTC).isoformat(),
            eligible_at_cutoff=False,
        )
    journal.record("captures", metadata, root)
    return metadata


if __name__ == "__main__":
    results = [
        run(zone, target, datetime.now(UTC).date() + timedelta(days=1))
        for zone, target in (
            ("SE3", "wind_solar"),
            ("DE_LU", "wind_solar"),
            ("DE_LU", "load"),
        )
    ]
    print(json.dumps(results, indent=2))
    raise SystemExit(any(result["status"] == "failed" for result in results))
