"""Configured data, results and settings paths for local and scheduled runs.

Set environment variables before importing pipeline modules. Defaults are relative
 to the working directory, never inferred from the installed source location.
"""

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("GRID_SIGNALS_RESEARCH_ROOT", "research")).resolve()
CONFIGS = Path(os.environ.get("GRID_SIGNALS_CONFIG_DIR", PACKAGE / "configs")).resolve()
DOCS = ROOT / "docs"
REPORTS = Path(os.environ.get("GRID_SIGNALS_REPORTS_DIR", ROOT / "reports")).resolve()
DATA = Path(os.environ.get("GRID_SIGNALS_DATA_DIR", ROOT / "data")).resolve()
OUTPUT = Path(os.environ.get("GRID_SIGNALS_OUTPUT_DIR", "data/exports")).resolve()
RAW = DATA / "raw"
PARSED = DATA / "parsed"
INTERIM = DATA / "interim"
FEATURES = DATA / "features"
PREDICTIONS = DATA / "predictions"
MLRUNS = Path(os.environ.get("GRID_SIGNALS_MLRUNS_DIR", ROOT / "mlruns")).resolve()
REQUEST_LEDGER = RAW / "requests_ledger.parquet"


def source_name(path: Path) -> str:
    """Name new source records independently of installation and volume paths."""
    path = path.resolve()
    if path.is_relative_to(CONFIGS):
        return "settings/" + str(path.relative_to(CONFIGS))
    if path.is_relative_to(PACKAGE):
        return "package/" + str(path.relative_to(PACKAGE))
    return str(path.relative_to(ROOT))


def source_path(name: str) -> Path:
    """Resolve new source names; historical paths keep their original meaning."""
    if name.startswith("package/"):
        return PACKAGE / name.removeprefix("package/")
    if name.startswith("settings/"):
        return CONFIGS / name.removeprefix("settings/")
    return ROOT / name


def ensure_data_dirs() -> None:
    for path in (RAW, PARSED, INTERIM, FEATURES, PREDICTIONS, MLRUNS, OUTPUT, REPORTS):
        path.mkdir(parents=True, exist_ok=True)
