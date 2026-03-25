"""DDL for all grid-signals tables.

Calling ``create_tables`` is idempotent — it uses CREATE TABLE IF NOT EXISTS.
"""

import duckdb

DDL_STATEMENTS: list[str] = [
    # --- energy ---
    """
    CREATE TABLE IF NOT EXISTS day_ahead_prices (
        zone          VARCHAR NOT NULL,
        period_start  TIMESTAMPTZ NOT NULL,
        period_end    TIMESTAMPTZ NOT NULL,
        price_eur_mwh DOUBLE NOT NULL,
        PRIMARY KEY (zone, period_start)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generation_by_type (
        zone          VARCHAR NOT NULL,
        period_start  TIMESTAMPTZ NOT NULL,
        period_end    TIMESTAMPTZ NOT NULL,
        fuel_type     VARCHAR NOT NULL,
        generation_mw DOUBLE NOT NULL,
        PRIMARY KEY (zone, period_start, fuel_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS total_load (
        zone         VARCHAR NOT NULL,
        period_start TIMESTAMPTZ NOT NULL,
        period_end   TIMESTAMPTZ NOT NULL,
        load_mw      DOUBLE NOT NULL,
        is_forecast  BOOLEAN NOT NULL,
        PRIMARY KEY (zone, period_start, is_forecast)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cross_border_flows (
        from_zone    VARCHAR NOT NULL,
        to_zone      VARCHAR NOT NULL,
        period_start TIMESTAMPTZ NOT NULL,
        period_end   TIMESTAMPTZ NOT NULL,
        flow_mw      DOUBLE NOT NULL,
        PRIMARY KEY (from_zone, to_zone, period_start)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS outages (
        message_id     VARCHAR PRIMARY KEY,
        zone           VARCHAR NOT NULL,
        asset_name     VARCHAR NOT NULL,
        fuel_type      VARCHAR NOT NULL,
        outage_type    VARCHAR NOT NULL,
        unavailable_mw DOUBLE NOT NULL,
        period_start   TIMESTAMPTZ NOT NULL,
        period_end     TIMESTAMPTZ
    )
    """,
    # --- weather ---
    """
    CREATE TABLE IF NOT EXISTS weather_forecasts (
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
    """,
]


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Execute all DDL statements to create tables (idempotent)."""
    for ddl in DDL_STATEMENTS:
        con.execute(ddl)
