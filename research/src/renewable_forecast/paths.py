"""Every filesystem path the project uses, constructed in one place."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONFIGS = ROOT / "configs"
DOCS = ROOT / "docs"
REPORTS = ROOT / "reports"

DATA = ROOT / "data"
RAW = DATA / "raw"
PARSED = DATA / "parsed"
INTERIM = DATA / "interim"
FEATURES = DATA / "features"
PREDICTIONS = DATA / "predictions"

MLRUNS = ROOT / "mlruns"

#: Maps a request's parameter hash to the params and the time it was fetched, so a
#: parser bug costs zero API calls to fix and every pull is resumable.
REQUEST_LEDGER = RAW / "requests_ledger.parquet"

#: DuckDB holds views over the parquet tree plus small dimension tables. It is
#: rebuildable in seconds and never needs backing up.
WAREHOUSE = DATA / "warehouse.duckdb"


def ensure_data_dirs() -> None:
    """Create the gitignored data directories if they are missing."""
    for path in (RAW, PARSED, INTERIM, FEATURES, PREDICTIONS, MLRUNS):
        path.mkdir(parents=True, exist_ok=True)
