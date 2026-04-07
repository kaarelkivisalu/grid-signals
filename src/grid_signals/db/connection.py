import psycopg

from grid_signals.config import get_database_url


def get_connection(
    dsn: str | None = None,
    *,
    read_only: bool = False,
) -> psycopg.Connection:
    """Open a PostgreSQL connection and return it.

    Uses DATABASE_URL from the environment when *dsn* is not provided.
    Connections use autocommit mode by default.  Callers that need transactions should use ``con.transaction()``.
    """
    if dsn is None:
        dsn = get_database_url()
    con = psycopg.connect(dsn, autocommit=True)
    if read_only:
        con.execute("SET default_transaction_read_only = on")
    return con


def get_read_connection(dsn: str | None = None) -> psycopg.Connection:
    """Open a read-only connection."""
    return get_connection(dsn, read_only=True)
