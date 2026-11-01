"""Small immutable JSON records for scheduled jobs and public-forecast captures."""

import json
from pathlib import Path
from uuid import uuid4

from grid_signals.forecast import paths

ROOT = paths.DATA / "operational"


def record(kind: str, payload: dict, root: Path = ROOT) -> Path:
    directory = root / kind
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{uuid4()}.json"
    temporary = destination.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False, default=str)
    temporary.replace(destination)
    return destination


def read(kind: str, root: Path = ROOT) -> list[dict]:
    return [
        json.loads(path.read_text()) for path in sorted((root / kind).glob("*.json"))
    ]
