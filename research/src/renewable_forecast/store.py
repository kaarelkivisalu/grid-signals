"""Storage layer: parquet is the source of truth, DuckDB is a query engine over it.

The warehouse holds views only, so it can be deleted and rebuilt in seconds and never
needs backing up.
"""

from pathlib import Path

import duckdb

from renewable_forecast import paths

#: View name -> glob of the parquet files backing it.
VIEWS: dict[str, Path] = {
    "actuals": paths.PARSED / "entsoe_actual" / "**" / "*.parquet",
    "capacity": paths.PARSED / "entsoe_capacity" / "**" / "*.parquet",
    "da_forecast": paths.PARSED / "entsoe_da_forecast" / "**" / "*.parquet",
    "nwp": paths.PARSED / "openmeteo" / "**" / "*.parquet",
    "era5": paths.PARSED / "era5" / "**" / "*.parquet",
    "targets": paths.INTERIM / "targets.parquet",
    "design_matrix": paths.FEATURES / "design_matrix.parquet",
}


def connect(*, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the warehouse, creating the data directories if needed."""
    paths.ensure_data_dirs()
    return duckdb.connect(str(paths.WAREHOUSE), read_only=read_only)


def rebuild_views(con: duckdb.DuckDBPyConnection) -> list[str]:
    """(Re)create a view per entry in `VIEWS` that has at least one parquet file.

    Returns the names of the views that were created.
    """
    created = []
    for name, glob in VIEWS.items():
        matches = list(glob.parent.rglob(glob.name)) if "*" in str(glob) else [glob]
        if not any(path.exists() for path in matches):
            continue
        con.execute(
            f"CREATE OR REPLACE VIEW {name} AS "
            f"SELECT * FROM read_parquet('{glob}', union_by_name = true)"
        )
        created.append(name)
    return created
