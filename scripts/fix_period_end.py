"""Fix period_end for 15-minute resolution data.

The period_start/period_end migration set period_end = period_start + 1 hour
for ALL data, but post-ISP-transition data has 15-minute periods.

This script detects the transition point per zone per table (first :15/:30/:45
entry) and fixes all rows from that point onward to use 15-minute intervals.

    uv run python scripts/fix_period_end.py [--db PATH] [--dry-run]
"""

import argparse
from pathlib import Path

import duckdb

# Tables to fix and their zone column name
TABLES = {
    "day_ahead_prices": "zone",
    "generation_by_type": "zone",
    "total_load": "zone",
    "cross_border_flows": "from_zone",
}


def fix_period_end(con: duckdb.DuckDBPyConnection, *, dry_run: bool) -> None:
    for table, zone_col in TABLES.items():
        print(f"\n=== {table} ===")

        # Find the first 15-min timestamp per zone
        transitions = con.execute(f"""
            SELECT {zone_col}, MIN(period_start) as first_15m
            FROM {table}
            WHERE EXTRACT(MINUTE FROM period_start) NOT IN (0)
            GROUP BY {zone_col}
        """).fetchall()

        if not transitions:
            print("  No 15-min data found, skipping.")
            continue

        for zone, first_15m in transitions:
            # The transition starts at the :00 of the same hour as the first :15
            # Actually, use the first :00 entry that's within 1 hour before the first :15
            # Simplest: the transition starts at the :00 just before the first :15
            transition_start = con.execute(
                f"""
                SELECT MAX(period_start) FROM {table}
                WHERE {zone_col} = ?
                  AND EXTRACT(MINUTE FROM period_start) = 0
                  AND period_start <= ?
            """,
                [zone, first_15m],
            ).fetchone()[0]

            if transition_start is None:
                transition_start = first_15m

            # Count rows to fix
            count = con.execute(
                f"""
                SELECT COUNT(*) FROM {table}
                WHERE {zone_col} = ?
                  AND period_start >= ?
                  AND period_end - period_start = INTERVAL '1 hour'
            """,
                [zone, transition_start],
            ).fetchone()[0]

            print(f"  {zone}: transition at {transition_start}, {count} rows to fix")

            if not dry_run and count > 0:
                con.execute(
                    f"""
                    UPDATE {table}
                    SET period_end = period_start + INTERVAL '15 minutes'
                    WHERE {zone_col} = ?
                      AND period_start >= ?
                      AND period_end - period_start = INTERVAL '1 hour'
                """,
                    [zone, transition_start],
                )
                print(f"  {zone}: fixed {count} rows")

    if dry_run:
        print("\n(dry run — no changes made)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix period_end for 15-min data")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).parent.parent / "data" / "grid_signals.duckdb"),
        help="Path to DuckDB file",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would change")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    con = duckdb.connect(str(db_path))
    try:
        fix_period_end(con, dry_run=args.dry_run)
    finally:
        con.close()


if __name__ == "__main__":
    main()
