"""Dashboard page — interactive data visualizations."""

from datetime import UTC, datetime, timedelta

import duckdb
import streamlit as st

from grid_signals.app.charts import (
    cross_border_flows,
    flow_map,
    generation_mix,
    hourly_prices,
    price_heatmap,
    wind_vs_price,
)
from grid_signals.db.connection import get_read_connection

st.set_page_config(page_title="Dashboard — Grid Signals", page_icon="⚡", layout="wide")
st.title("Dashboard")

ZONES = [
    "EE",
    "LV",
    "LT",
    "FI",
    "SE1",
    "SE2",
    "SE3",
    "SE4",
    "NO1",
    "NO2",
    "NO3",
    "NO4",
    "NO5",
    "DK1",
    "DK2",
]
# Map display zone codes to DB (ENTSO-E) codes for cross-border flow queries.
_ZONE_TO_DB: dict[str, str] = {
    z: z if len(z) == 2 else f"{z[:2]}_{z[2:]}" for z in ZONES
}
WEATHER_LOCATIONS = [
    "EE_tallinn",
    "LV_riga",
    "LT_kaunas",
    "FI_inland",
    "FI_ostrobothnia",
    "SE1_lulea",
    "SE2_sundsvall",
    "SE3_central",
    "SE4_skane",
    "NO1_oslo",
    "NO2_kristiansand",
    "NO3_trondheim",
    "NO4_tromso",
    "NO5_bergen",
    "DK1_jutland",
    "DK2_zealand",
]


@st.cache_resource
def get_dash_db() -> duckdb.DuckDBPyConnection:
    """Read-only DB connection for the dashboard."""
    return get_read_connection()


try:
    con = get_dash_db()
except duckdb.IOException:
    st.warning(
        "Data ingestion is currently running. The dashboard will be available "
        "once ingestion completes. Refresh the page to retry.",
        icon="\u23f3",
    )
    st.stop()

# --- Date range selector (shared) ---
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input(
        "Start date", value=datetime.now(tz=UTC).date() - timedelta(days=7)
    )
with col2:
    end_date = st.date_input(
        "End date", value=datetime.now(tz=UTC).date() + timedelta(days=1)
    )

start_str = start_date.isoformat()
end_str = end_date.isoformat()

# --- Tabs for chart types ---
tab1, tab2, tab3, tab_map, tab4, tab5 = st.tabs(
    [
        "Hourly Prices",
        "Generation Mix",
        "Cross-Border Flows",
        "Flow Map",
        "Wind vs Price",
        "Price Heatmap",
    ]
)

with tab1:
    selected_zones = st.multiselect("Zones", ZONES, default=["EE", "FI", "LT"])
    if selected_zones:
        fig = hourly_prices(con, selected_zones, start_str, end_str)
        st.plotly_chart(fig, width="stretch")

with tab2:
    zone = st.selectbox("Zone", ZONES, key="gen_zone")
    fig = generation_mix(con, zone, start_str, end_str)
    st.plotly_chart(fig, width="stretch")

with tab3:
    flow_zone = st.selectbox("Zone", ZONES, key="flow_zone")
    fig = cross_border_flows(con, _ZONE_TO_DB[flow_zone], start_str, end_str)
    st.plotly_chart(fig, width="stretch")

with tab_map:
    fig = flow_map(con, start_str, end_str)
    st.plotly_chart(fig, use_container_width=True)

with tab4:
    wcol1, wcol2 = st.columns(2)
    with wcol1:
        w_zone = st.selectbox("Zone", ZONES, key="wind_zone")
    with wcol2:
        w_loc = st.selectbox("Weather location", WEATHER_LOCATIONS, key="wind_loc")
    fig = wind_vs_price(con, w_zone, w_loc, start_str, end_str)
    st.plotly_chart(fig, width="stretch")

with tab5:
    hm_date = st.date_input(
        "Date", value=datetime.now(tz=UTC).date() - timedelta(days=1), key="hm_date"
    )
    hm_zones = st.multiselect("Zones", ZONES, default=ZONES, key="hm_zones")
    if hm_zones:
        fig = price_heatmap(con, hm_zones, hm_date.isoformat())
        st.plotly_chart(fig, width="stretch")
