"""Identify consolidated code without rewriting historical model version records."""

import hashlib
import json
import os
from pathlib import Path

from grid_signals.forecast import paths

RECORD = Path(
    os.environ.get(
        "GRID_SIGNALS_VERSION_RECORD", paths.CONFIGS / "releases/consolidated_v1.json"
    )
)


def sources() -> dict[str, str]:
    files = [
        *paths.PACKAGE.rglob("*.py"),
        *paths.CONFIGS.glob("*.yaml"),
        *paths.CONFIGS.glob("*.csv"),
        *paths.CONFIGS.glob("*.geojson"),
        *paths.CONFIGS.glob("experiments/*.yaml"),
    ]
    files.extend(paths.PACKAGE.parent / name for name in ("products.py", "markets.py"))
    return {
        (
            "shared/" + path.name
            if path.parent == paths.PACKAGE.parent
            else paths.source_name(path)
        ): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }


def register(destination: Path) -> dict:
    """Create a new code version record; existing records cannot be overwritten."""
    evidence = paths.ROOT / "configs/releases"
    lineage = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(evidence.glob("*.json"))
    }
    protocol = paths.INTERIM / "load_protocol.json"
    record = {
        "version": "consolidated-v1",
        "sources": sources(),
        "historical_records": lineage,
        "historical_load_selection_sha256": hashlib.sha256(
            protocol.read_bytes()
        ).hexdigest()
        if protocol.exists()
        else None,
        "meaning": "Source consolidation verified against fixed-input predictions and metrics; no new holdout evaluation or saved-model promotion.",
    }
    record["identity"] = (
        "consolidated-v1+"
        + hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:16]
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    return record


def verify() -> dict:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    if record["sources"] != sources():
        message = "Consolidated sources/settings differ from the model version record; register and verify a new version before publication."
        raise RuntimeError(message)
    return record
