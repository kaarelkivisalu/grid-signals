import time
from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path("data/grid_signals.duckdb")


def get_connection(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Open (or create) a DuckDB database and return a connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path), read_only=read_only)


def get_read_connection(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    retries: int = 3,
    delay: float = 1.0,
) -> duckdb.DuckDBPyConnection:
    """Open a read-only connection, retrying if a writer holds the lock."""
    for attempt in range(retries):
        try:
            return duckdb.connect(str(db_path), read_only=True)
        except duckdb.IOException:
            if attempt < retries - 1:
                time.sleep(delay)
    msg = "Database is locked by a running ingestion process."
    raise duckdb.IOException(msg)
