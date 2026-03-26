"""Grid Signals — main Streamlit entry point."""

from datetime import UTC, datetime

import duckdb
import streamlit as st

from grid_signals.db.connection import DEFAULT_DB_PATH
from grid_signals.db.schema import create_tables

st.set_page_config(
    page_title="Grid Signals",
    page_icon="⚡",
    layout="wide",
)

# --- Shared DB connection (read-only) ---


@st.cache_resource
def get_db() -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection, shared across all pages."""
    con = duckdb.connect(str(DEFAULT_DB_PATH), read_only=True)
    create_tables(con)
    return con


# --- Sidebar ---

st.sidebar.title("⚡ Grid Signals")
st.sidebar.caption("Nordic-Baltic Energy Intelligence")

con = get_db()
try:
    tables = ["day_ahead_prices", "generation_by_type", "total_load",
              "cross_border_flows", "outages", "weather_forecasts"]
    st.sidebar.markdown("---")
    st.sidebar.subheader("Database")
    for table in tables:
        try:
            count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
            st.sidebar.metric(table.replace("_", " ").title(), f"{count:,} rows")
        except duckdb.CatalogException:
            st.sidebar.metric(table.replace("_", " ").title(), "—")
except Exception:
    st.sidebar.warning("Could not read database stats.")

st.sidebar.markdown("---")
st.sidebar.caption(f"UTC: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}")

# --- Main page ---

st.title("Grid Signals")
st.markdown(
    "Nordic-Baltic energy intelligence agent. "
    "Use the sidebar to navigate between pages."
)
st.markdown("""
### Pages

- **Briefings** — View saved daily briefings
- **Chat** — Ask the energy intelligence agent questions
- **Dashboard** — Interactive price, generation, and weather charts
""")
