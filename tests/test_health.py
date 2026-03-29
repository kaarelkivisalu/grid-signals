"""Tests for health check module."""

from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from grid_signals.health import check_data_freshness


@pytest.fixture()
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute("""
        CREATE TABLE day_ahead_prices (period_start TIMESTAMPTZ, period_end TIMESTAMPTZ, zone VARCHAR, price_eur_mwh DOUBLE);
        CREATE TABLE generation_by_type (period_start TIMESTAMPTZ, period_end TIMESTAMPTZ, zone VARCHAR, fuel_type VARCHAR, value_mw DOUBLE);
        CREATE TABLE total_load (period_start TIMESTAMPTZ, period_end TIMESTAMPTZ, zone VARCHAR, load_mw DOUBLE);
        CREATE TABLE cross_border_flows (period_start TIMESTAMPTZ, period_end TIMESTAMPTZ, from_zone VARCHAR, to_zone VARCHAR, flow_mw DOUBLE);
    """)
    return c


def test_empty_tables_unhealthy(con: duckdb.DuckDBPyConnection) -> None:
    status = check_data_freshness(con)
    assert not status.healthy
    assert all(not c.ok for c in status.checks)


def _insert_all(con: duckdb.DuckDBPyConnection, ts: datetime) -> None:
    """Insert a row into each table with the given timestamp."""
    con.execute(
        "INSERT INTO day_ahead_prices VALUES (?, ?, 'EE', 0)", [ts, ts]
    )
    con.execute(
        "INSERT INTO generation_by_type VALUES (?, ?, 'EE', 'wind', 0)", [ts, ts]
    )
    con.execute(
        "INSERT INTO total_load VALUES (?, ?, 'EE', 0)", [ts, ts]
    )
    con.execute(
        "INSERT INTO cross_border_flows VALUES (?, ?, 'EE', 'FI', 0)", [ts, ts]
    )


def test_fresh_data_healthy(con: duckdb.DuckDBPyConnection) -> None:
    _insert_all(con, datetime.now(UTC))
    status = check_data_freshness(con)
    assert status.healthy


def test_stale_data_unhealthy(con: duckdb.DuckDBPyConnection) -> None:
    _insert_all(con, datetime.now(UTC) - timedelta(hours=48))
    status = check_data_freshness(con, max_age_hours=26)
    assert not status.healthy
