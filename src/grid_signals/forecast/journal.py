"""Small immutable JSON records for scheduled jobs and public-forecast captures."""

import json
from pathlib import Path
from uuid import uuid4

from grid_signals.forecast import paths
from grid_signals.forecast.storage import atomic_json

ROOT = paths.DATA / "operational"


def record(kind: str, payload: dict, root: Path = ROOT) -> Path:
    directory = root / kind
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{uuid4()}.json"
    atomic_json(destination, payload)
    return destination


def read(kind: str, root: Path = ROOT) -> list[dict]:
    return [
        json.loads(path.read_text()) for path in sorted((root / kind).glob("*.json"))
    ]
