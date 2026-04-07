"""Shared test fixtures — PostgreSQL via testcontainers."""

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from grid_signals.db.schema import create_tables

_PG_IMAGE = "postgres:17"


@pytest.fixture(scope="session")
def pg_container():
    """Start a PostgreSQL container once per test session."""
    with PostgresContainer(_PG_IMAGE) as pg:
        yield pg


@pytest.fixture
def con(pg_container):
    """Fresh PostgreSQL connection with all tables created.

    Each test gets its own connection. Tables are dropped and recreated
    so tests don't leak state.
    """
    dsn = pg_container.get_connection_url().replace("+psycopg2", "")
    conn = psycopg.connect(dsn, autocommit=True)
    # Drop and recreate all tables for a clean slate
    conn.execute("""
        DROP TABLE IF EXISTS day_ahead_prices CASCADE;
        DROP TABLE IF EXISTS generation_by_type CASCADE;
        DROP TABLE IF EXISTS total_load CASCADE;
        DROP TABLE IF EXISTS cross_border_flows CASCADE;
        DROP TABLE IF EXISTS outages CASCADE;
        DROP TABLE IF EXISTS weather_forecasts CASCADE;
        DROP TABLE IF EXISTS briefings CASCADE;
    """)
    create_tables(conn)
    yield conn
    conn.close()
