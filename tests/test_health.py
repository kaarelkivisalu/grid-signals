"""Tests for health check module."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from grid_signals.health import check_data_freshness


@pytest.fixture
def health_con(pg_container):
    """Connection with minimal tables for health check tests."""
    dsn = pg_container.get_connection_url().replace("+psycopg2", "")
    conn = psycopg.connect(dsn, autocommit=True)
    conn.execute("""
        DROP TABLE IF EXISTS day_ahead_prices CASCADE;
        DROP TABLE IF EXISTS generation_by_type CASCADE;
        DROP TABLE IF EXISTS total_load CASCADE;
        DROP TABLE IF EXISTS cross_border_flows CASCADE;
    """)
    conn.execute("""
        CREATE TABLE day_ahead_prices (period_start TIMESTAMPTZ, period_end TIMESTAMPTZ, zone VARCHAR, price_eur_mwh DOUBLE PRECISION);
        CREATE TABLE generation_by_type (period_start TIMESTAMPTZ, period_end TIMESTAMPTZ, zone VARCHAR, fuel_type VARCHAR, value_mw DOUBLE PRECISION);
        CREATE TABLE total_load (period_start TIMESTAMPTZ, period_end TIMESTAMPTZ, zone VARCHAR, load_mw DOUBLE PRECISION);
        CREATE TABLE cross_border_flows (period_start TIMESTAMPTZ, period_end TIMESTAMPTZ, from_zone VARCHAR, to_zone VARCHAR, flow_mw DOUBLE PRECISION);
    """)
    yield conn
    conn.close()


def test_empty_tables_unhealthy(health_con) -> None:
    status = check_data_freshness(health_con)
    assert not status.healthy
    assert all(not c.ok for c in status.checks)


def _insert_all(con: psycopg.Connection, ts: datetime) -> None:
    """Insert a row into each table with the given timestamp."""
    con.execute("INSERT INTO day_ahead_prices VALUES (%s, %s, 'EE', 0)", [ts, ts])
    con.execute(
        "INSERT INTO generation_by_type VALUES (%s, %s, 'EE', 'wind', 0)", [ts, ts]
    )
    con.execute("INSERT INTO total_load VALUES (%s, %s, 'EE', 0)", [ts, ts])
    con.execute(
        "INSERT INTO cross_border_flows VALUES (%s, %s, 'EE', 'FI', 0)", [ts, ts]
    )


def test_fresh_data_healthy(health_con) -> None:
    _insert_all(health_con, datetime.now(UTC))
    status = check_data_freshness(health_con)
    assert status.healthy


def test_stale_data_unhealthy(health_con) -> None:
    _insert_all(health_con, datetime.now(UTC) - timedelta(hours=48))
    status = check_data_freshness(health_con, max_age_hours=26)
    assert not status.healthy
