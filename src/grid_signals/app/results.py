"""Read one checked public generation; preserve bundled historical recovery."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from operator import itemgetter
from pathlib import Path

DEFAULT = Path(__file__).parent / "assets"


def checked_generation(public: Path, filename: str) -> tuple[Path, dict]:
    pointer = json.loads((public / filename).read_text())
    identity = pointer["generation"]
    if (
        pointer["schema_version"] != 1
        or Path(identity).name != identity
        or identity in {".", ".."}
    ):
        message = "Invalid result generation"
        raise ValueError(message)
    root = public / "generations" / identity
    index = root / "files.json"
    if hashlib.sha256(index.read_bytes()).hexdigest() != pointer["index_sha256"]:
        message = "Result index checksum mismatch"
        raise ValueError(message)
    files = json.loads(index.read_text())
    required = {
        "explorer/manifest.json",
        "publication.json",
        "forecast_snapshot.json",
        "price_snapshot.json",
        "load_snapshot.json",
    }
    if not required.issubset(files):
        message = "Incomplete result generation"
        raise ValueError(message)
    for receipt in pointer.get("deliveries", {}).values():
        if receipt["publication_status"] not in {
            "on_time",
            "late",
            "early",
            "retrospective",
            "pending_delivery",
        }:
            message = "Invalid publication status"
            raise ValueError(message)
        if receipt["publication_status"] != "pending_delivery":
            datetime.fromisoformat(receipt["published_at"])
    for name, checksum in files.items():
        file = root / name
        if (
            not file.resolve().is_relative_to(root.resolve())
            or hashlib.sha256(file.read_bytes()).hexdigest() != checksum
        ):
            message = "Result file checksum mismatch"
            raise ValueError(message)
    return root, pointer


def selected() -> tuple[Path, dict, str | None]:
    configured = os.environ.get("GRID_SIGNALS_RESULT_ROOT")
    if not configured:
        return DEFAULT, {}, None
    public = Path(configured)
    error = None
    for name in ("current.json", "previous.json"):
        try:
            root, pointer = checked_generation(public, name)
        except (OSError, ValueError, KeyError, TypeError):
            error = "The latest daily update is unavailable. Showing the last checked results."
        else:
            return root, pointer, error
    return DEFAULT, {}, error


def publication_record(
    root: Path, pointer: dict, *, now: datetime | None = None
) -> dict:
    file = root / "publication.json"
    if not file.exists():
        return {"status": "not_started", "issues": []}
    record = json.loads(file.read_text())
    now = now or datetime.now(UTC)
    receipts = pointer.get("deliveries", {})
    for row in record["issues"]:
        receipt = receipts.get(row.get("forecast_id"))
        if receipt:
            row["published_at"] = receipt["published_at"]
            row["status"] = receipt["publication_status"]
            if row["status"] != "on_time":
                row["score"] = None
            row["jobs"]["delivery"] = {
                "status": "completed",
                "at": receipt["published_at"],
            }
        # Missing days must remain visible even when the runner has stopped exporting.
    start = record.get("first_issue_day")
    if start:
        known = {row["issue_day"] for row in record["issues"]}
        day = datetime.fromisoformat(start).date()
        while day <= now.date():
            if day.isoformat() not in known:
                deadline = datetime.combine(day, datetime.min.time(), UTC) + timedelta(
                    hours=9, minutes=30
                )
                record["issues"].append(
                    {
                        "issue_day": day.isoformat(),
                        "delivery_day": (day + timedelta(days=1)).isoformat(),
                        "deadline_at": deadline.isoformat(),
                        "status": "missing" if now > deadline else "pending",
                        "published_at": None,
                        "forecast_id": None,
                        "score": None,
                        "jobs": {},
                    }
                )
            day += timedelta(days=1)
    record["issues"].sort(key=itemgetter("issue_day"))
    record["snapshot_stale"] = now - datetime.fromisoformat(
        pointer["committed_at"]
    ) > timedelta(minutes=45)
    consecutive = 0
    for row in reversed(
        [
            row
            for row in record["issues"]
            if datetime.fromisoformat(row["deadline_at"]) < now
        ]
    ):
        if row["status"] != "on_time":
            break
        consecutive += 1
    record["reliability_gate"] = {
        "required_consecutive_issues": 30,
        "consecutive_on_time": consecutive,
        "met": consecutive >= 30,
    }
    return record
