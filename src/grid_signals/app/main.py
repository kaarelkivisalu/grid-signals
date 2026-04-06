"""Grid Signals — main Streamlit entry point."""

import duckdb
import streamlit as st

from grid_signals.db.connection import get_read_connection

st.set_page_config(
    page_title="Grid Signals",
    page_icon="⚡",
    layout="wide",
)

# --- Shared DB connection (read-only) ---


@st.cache_resource
def get_db() -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection, shared across all pages."""
    return get_read_connection()


# --- Sidebar & Navigation ---

pages = st.navigation(
    [
        st.Page("pages/overview.py", title="Overview", icon="🏠", default=True),
        st.Page("pages/1_briefings.py", title="Briefings", icon="📋"),
        st.Page("pages/2_chat.py", title="Chat", icon="💬"),
        st.Page("pages/3_dashboard.py", title="Dashboard", icon="📊"),
    ],
)

st.sidebar.title("⚡ Grid Signals")
st.sidebar.caption("Nordic-Baltic Energy Intelligence")

pages.run()
