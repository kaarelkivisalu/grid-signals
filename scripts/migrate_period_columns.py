"""One-time migration: rename timestamp columns to period_start/period_end.

Run once against an existing database:

    uv run python scripts/migrate_period_columns.py [--db PATH]

For each table the script:
1. Creates a new table with the updated schema (period_start, period_end, correct PK).
2. Copies all existing rows, setting period_end = period_start + INTERVAL '1 hour'
   (all pre-migration data is hourly).
3. Drops the old table and renames the new one.

Idempotent: if the new columns already exist (migration already ran), the
script prints a message and exits cleanly.
"""

import argparse
import sys
from pathlib import Path

import duckdb


def already_migrated(con: duckdb.DuckDBPyConnection) -> bool:
    """Return True if day_ahead_prices already has period_start (migration done)."""
    cols = {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'day_ahead_prices'"
        ).fetchall()
    }
    return "period_start" in cols


def migrate(con: duckdb.DuckDBPyConnection) -> None:
    print("Starting migration: timestamp → period_start/period_end")

    con.execute("BEGIN")
    try:
        # ----------------------------------------------------------------
        # day_ahead_prices
        # ----------------------------------------------------------------
        before = con.execute("SELECT COUNT(*) FROM day_ahead_prices").fetchone()[0]
        con.execute("""
            CREATE TABLE day_ahead_prices_new (
                zone          VARCHAR NOT NULL,
                period_start  TIMESTAMPTZ NOT NULL,
                period_end    TIMESTAMPTZ NOT NULL,
                price_eur_mwh DOUBLE NOT NULL,
                PRIMARY KEY (zone, period_start)
            )
        """)
        con.execute("""
            INSERT INTO day_ahead_prices_new
            SELECT zone,
                   timestamp AS period_start,
                   timestamp + INTERVAL '1 hour' AS period_end,
                   price_eur_mwh
            FROM day_ahead_prices
        """)
        con.execute("DROP TABLE day_ahead_prices")
        con.execute("ALTER TABLE day_ahead_prices_new RENAME TO day_ahead_prices")
        after = con.execute("SELECT COUNT(*) FROM day_ahead_prices").fetchone()[0]
        print(f"  day_ahead_prices: {before} → {after} rows")

        # ----------------------------------------------------------------
        # generation_by_type
        # ----------------------------------------------------------------
        before = con.execute("SELECT COUNT(*) FROM generation_by_type").fetchone()[0]
        con.execute("""
            CREATE TABLE generation_by_type_new (
                zone          VARCHAR NOT NULL,
                period_start  TIMESTAMPTZ NOT NULL,
                period_end    TIMESTAMPTZ NOT NULL,
                fuel_type     VARCHAR NOT NULL,
                generation_mw DOUBLE NOT NULL,
                PRIMARY KEY (zone, period_start, fuel_type)
            )
        """)
        con.execute("""
            INSERT INTO generation_by_type_new
            SELECT zone,
                   timestamp AS period_start,
                   timestamp + INTERVAL '1 hour' AS period_end,
                   fuel_type, generation_mw
            FROM generation_by_type
        """)
        con.execute("DROP TABLE generation_by_type")
        con.execute("ALTER TABLE generation_by_type_new RENAME TO generation_by_type")
        after = con.execute("SELECT COUNT(*) FROM generation_by_type").fetchone()[0]
        print(f"  generation_by_type: {before} → {after} rows")

        # ----------------------------------------------------------------
        # total_load
        # ----------------------------------------------------------------
        before = con.execute("SELECT COUNT(*) FROM total_load").fetchone()[0]
        con.execute("""
            CREATE TABLE total_load_new (
                zone         VARCHAR NOT NULL,
                period_start TIMESTAMPTZ NOT NULL,
                period_end   TIMESTAMPTZ NOT NULL,
                load_mw      DOUBLE NOT NULL,
                is_forecast  BOOLEAN NOT NULL,
                PRIMARY KEY (zone, period_start, is_forecast)
            )
        """)
        con.execute("""
            INSERT INTO total_load_new
            SELECT zone,
                   timestamp AS period_start,
                   timestamp + INTERVAL '1 hour' AS period_end,
                   load_mw, is_forecast
            FROM total_load
        """)
        con.execute("DROP TABLE total_load")
        con.execute("ALTER TABLE total_load_new RENAME TO total_load")
        after = con.execute("SELECT COUNT(*) FROM total_load").fetchone()[0]
        print(f"  total_load: {before} → {after} rows")

        # ----------------------------------------------------------------
        # cross_border_flows
        # ----------------------------------------------------------------
        before = con.execute("SELECT COUNT(*) FROM cross_border_flows").fetchone()[0]
        con.execute("""
            CREATE TABLE cross_border_flows_new (
                from_zone    VARCHAR NOT NULL,
                to_zone      VARCHAR NOT NULL,
                period_start TIMESTAMPTZ NOT NULL,
                period_end   TIMESTAMPTZ NOT NULL,
                flow_mw      DOUBLE NOT NULL,
                PRIMARY KEY (from_zone, to_zone, period_start)
            )
        """)
        con.execute("""
            INSERT INTO cross_border_flows_new
            SELECT from_zone, to_zone,
                   timestamp AS period_start,
                   timestamp + INTERVAL '1 hour' AS period_end,
                   flow_mw
            FROM cross_border_flows
        """)
        con.execute("DROP TABLE cross_border_flows")
        con.execute("ALTER TABLE cross_border_flows_new RENAME TO cross_border_flows")
        after = con.execute("SELECT COUNT(*) FROM cross_border_flows").fetchone()[0]
        print(f"  cross_border_flows: {before} → {after} rows")

        # ----------------------------------------------------------------
        # outages  (start_time/end_time → period_start/period_end)
        # ----------------------------------------------------------------
        before = con.execute("SELECT COUNT(*) FROM outages").fetchone()[0]
        con.execute("""
            CREATE TABLE outages_new (
                message_id     VARCHAR PRIMARY KEY,
                zone           VARCHAR NOT NULL,
                asset_name     VARCHAR NOT NULL,
                fuel_type      VARCHAR NOT NULL,
                outage_type    VARCHAR NOT NULL,
                unavailable_mw DOUBLE NOT NULL,
                period_start   TIMESTAMPTZ NOT NULL,
                period_end     TIMESTAMPTZ
            )
        """)
        con.execute("""
            INSERT INTO outages_new
            SELECT message_id, zone, asset_name, fuel_type, outage_type,
                   unavailable_mw,
                   start_time AS period_start,
                   end_time   AS period_end
            FROM outages
        """)
        con.execute("DROP TABLE outages")
        con.execute("ALTER TABLE outages_new RENAME TO outages")
        after = con.execute("SELECT COUNT(*) FROM outages").fetchone()[0]
        print(f"  outages: {before} → {after} rows")

        # ----------------------------------------------------------------
        # weather_forecasts
        # ----------------------------------------------------------------
        before = con.execute("SELECT COUNT(*) FROM weather_forecasts").fetchone()[0]
        con.execute("""
            CREATE TABLE weather_forecasts_new (
                location_name        VARCHAR NOT NULL,
                latitude             DOUBLE NOT NULL,
                longitude            DOUBLE NOT NULL,
                period_start         TIMESTAMPTZ NOT NULL,
                period_end           TIMESTAMPTZ NOT NULL,
                fetched_at           TIMESTAMPTZ NOT NULL,
                wind_speed_100m_ms   DOUBLE,
                solar_irradiance_wm2 DOUBLE,
                temperature_c        DOUBLE,
                PRIMARY KEY (location_name, period_start, fetched_at)
            )
        """)
        con.execute("""
            INSERT INTO weather_forecasts_new
            SELECT location_name, latitude, longitude,
                   timestamp AS period_start,
                   timestamp + INTERVAL '1 hour' AS period_end,
                   fetched_at,
                   wind_speed_100m_ms, solar_irradiance_wm2, temperature_c
            FROM weather_forecasts
        """)
        con.execute("DROP TABLE weather_forecasts")
        con.execute("ALTER TABLE weather_forecasts_new RENAME TO weather_forecasts")
        after = con.execute("SELECT COUNT(*) FROM weather_forecasts").fetchone()[0]
        print(f"  weather_forecasts: {before} → {after} rows")

        con.execute("COMMIT")
        print("Migration complete.")

    except Exception:
        con.execute("ROLLBACK")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate DB to period_start/period_end schema")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).parent.parent / "grid_signals.db"),
        help="Path to DuckDB file (default: grid_signals.db in project root)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    con = duckdb.connect(str(db_path))
    try:
        if already_migrated(con):
            print("Migration already applied (period_start column exists). Nothing to do.")
            return
        migrate(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
