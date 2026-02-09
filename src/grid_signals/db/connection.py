from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path("data/grid_signals.duckdb")


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (or create) a DuckDB database and return a connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))
