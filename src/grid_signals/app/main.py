"""Grid Signals — one market/date context across the research portfolio."""

import os
from datetime import date

import streamlit as st

from grid_signals.app.explorer_data import load_manifest, suggested_backtest_day
from grid_signals.app.markets import BY_CODE, MARKETS, SELECTED_MODELS, TARGETS
from grid_signals.app.model_catalogue import model_name
from grid_signals.app.snapshot import SnapshotError

st.set_page_config(
    page_title="Grid Signals · European power", page_icon="⚡", layout="wide"
)
st.markdown(
    """<style>
    .stApp { background: #f8faf9; }
    .block-container { max-width: 1320px; padding-top: 3.3rem; }
    h1, h2, h3 { color: #183c3b; letter-spacing: -0.025em; }
    h1 { font-size: 2.6rem; }
    [data-testid="stSidebar"] { background: #edf3f0; }
    [data-testid="stMetricValue"] { color: #183c3b; }
    [data-testid="stMetricLabel"] { color: #536963; }
    [data-testid="stCaptionContainer"] { color: #60736e; }
    [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }
    </style>""",
    unsafe_allow_html=True,
)
st.sidebar.title("Grid Signals")
st.sidebar.caption("EUROPEAN POWER · FORECAST RESEARCH")
try:
    manifest = load_manifest()
except SnapshotError:
    st.title("Grid Signals")
    st.error("Market explorer unavailable")
    st.write("The exported research data is unavailable. Please try again later.")
    st.stop()
st.session_state.explorer_manifest = manifest

demo_only = os.environ.get("GRID_SIGNALS_DEMO_ONLY") == "1"
navigation = {
    "Research": [
        st.Page(
            "pages/overview.py",
            title="Market explorer",
            icon=":material/show_chart:",
            default=True,
        ),
        st.Page(
            "pages/performance.py", title="Performance", icon=":material/analytics:"
        ),
        st.Page("pages/coverage.py", title="European coverage", icon=":material/map:"),
        st.Page("pages/methods.py", title="Models & data", icon=":material/science:"),
    ]
}
if not demo_only and st.session_state.get("show_market_tools", False):
    navigation["Market tools"] = [
        st.Page(
            "pages/3_dashboard.py",
            title="Market dashboard",
            icon=":material/bar_chart:",
        ),
        st.Page("pages/1_briefings.py", title="Briefings", icon=":material/article:"),
        st.Page("pages/2_chat.py", title="Chat", icon=":material/chat:"),
    ]
pages = st.navigation(navigation)

if "pending_zone" in st.session_state:
    st.session_state.selected_zone = st.session_state.pop("pending_zone")
if "pending_date" in st.session_state:
    st.session_state.delivery_date = st.session_state.pop("pending_date")
if "selected_zone" not in st.session_state:
    st.session_state.selected_zone = "DE_LU"
st.sidebar.selectbox(
    "Market area",
    [m.code for m in MARKETS],
    format_func=lambda code: f"{code.replace('_', '-')} · {BY_CODE[code].name}",
    key="selected_zone",
)
zone = st.session_state.selected_zone
info = manifest["zones"].get(zone, {})
if "delivery_date" not in st.session_state:
    initial = (
        suggested_backtest_day(info)
        or (info.get("dates") or [manifest["exported_at"][:10]])[-1]
    )
    st.session_state.delivery_date = date.fromisoformat(initial)
st.sidebar.date_input(
    "Delivery date",
    key="delivery_date",
    help="Local market date. Choose any date; missing series are shown explicitly.",
)
if info.get("dates"):
    st.sidebar.caption(f"Archive: {info['dates'][0]} → {info['dates'][-1]}")
    if st.sidebar.button("Latest forecast / data", width="stretch"):
        st.session_state.pending_date = date.fromisoformat(info["dates"][-1])
        st.rerun()
joint_day = suggested_backtest_day(info)
if joint_day and st.sidebar.button("Latest joint backtest", width="stretch"):
    st.session_state.pending_date = date.fromisoformat(joint_day)
    st.rerun()
st.sidebar.selectbox(
    "Forecast target", list(TARGETS), format_func=TARGETS.get, key="selected_target"
)
target = st.session_state.selected_target
models = info.get("targets", {}).get(target, {}).get("models", [])
if st.session_state.get("selected_model") not in models:
    st.session_state.selected_model = (
        SELECTED_MODELS.get(target)
        if SELECTED_MODELS.get(target) in models
        else models[0]
        if models
        else None
    )
st.sidebar.selectbox(
    "Model",
    models or [None],
    format_func=lambda model: (
        model_name(model) if model else "No custom model in this area"
    ),
    key="selected_model",
    disabled=not models,
)
st.sidebar.caption(
    "Market, target and model stay selected across views. Delivery date controls the explorer; Performance has a scored date range."
)
if not demo_only:
    with st.sidebar.expander("More tools"):
        st.toggle("Show market tools", value=False, key="show_market_tools")
        st.caption(
            "The original operational tools require their database and API setup."
        )
st.sidebar.divider()
st.sidebar.caption(
    f"Data bundle: {manifest['exported_at'][:10]} · historical replay + publication archive"
)
st.sidebar.markdown("[Source code](https://github.com/kaarelkivisalu/grid-signals)")
pages.run()
