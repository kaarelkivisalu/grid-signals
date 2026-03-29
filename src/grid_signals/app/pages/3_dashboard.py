"""Dashboard page — interactive data visualizations."""

from datetime import date, timedelta

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
from grid_signals.db.connection import DEFAULT_DB_PATH

st.set_page_config(page_title="Dashboard — Grid Signals", page_icon="⚡", layout="wide")
st.title("Dashboard")

ZONES = ["EE", "LV", "LT", "FI", "SE1", "SE2", "SE3", "SE4", "NO1", "NO2", "NO3", "NO4", "NO5", "DK1", "DK2"]
INTERCONNECTORS = [
    ("FI", "EE"),
    ("EE", "LV"),
    ("LV", "LT"),
    ("SE4", "LT"),
    ("NO1", "SE3"),
    ("NO2", "DK1"),
    ("DK1", "DK2"),
    ("DK2", "SE4"),
    ("NO4", "FI"),
]
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
    return duckdb.connect(str(DEFAULT_DB_PATH), read_only=True)


con = get_dash_db()

# --- Date range selector (shared) ---
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start date", value=date.today() - timedelta(days=7))
with col2:
    end_date = st.date_input("End date", value=date.today() + timedelta(days=1))

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
    ic_labels = [f"{f} → {t}" for f, t in INTERCONNECTORS]
    ic_idx = st.selectbox(
        "Interconnector",
        range(len(INTERCONNECTORS)),
        format_func=lambda i: ic_labels[i],
        key="ic_select",
    )
    f_zone, t_zone = INTERCONNECTORS[ic_idx]
    fig = cross_border_flows(con, f_zone, t_zone, start_str, end_str)
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
        "Date", value=date.today() - timedelta(days=1), key="hm_date"
    )
    hm_zones = st.multiselect("Zones", ZONES, default=ZONES, key="hm_zones")
    if hm_zones:
        fig = price_heatmap(con, hm_zones, hm_date.isoformat())
        st.plotly_chart(fig, width="stretch")
