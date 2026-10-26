"""Grid Signals — one market/date context across the research portfolio."""

from datetime import date

import streamlit as st

from grid_signals.app.explorer_data import load_manifest, suggested_backtest_day
from grid_signals.app.markets import BY_CODE, MARKETS, SELECTED_MODELS, TARGETS
from grid_signals.app.model_catalogue import model_name
from grid_signals.app.snapshot import SnapshotError

st.set_page_config(page_title="Grid Signals · Nordic/Baltic forecasts", layout="wide")
st.markdown(
    """<style>
    .stApp { background: #f8faf9; }
    .block-container { max-width: 1320px; padding-top: 3.3rem; }
    h1, h2, h3 { color: #183c3b; letter-spacing: -0.025em; }
    h1 { font-size: 2.6rem; }
    [data-testid="stSidebar"] { background: #edf3f0; }
    [data-testid="stMetricValue"] { color: #183c3b; }
    [data-testid="stMetricLabel"] { color: #536963; }
    [data-testid="stCaptionContainer"] { opacity: 1; }
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p { color: #536963; }
    [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }
    </style>""",
    unsafe_allow_html=True,
)
st.sidebar.title("Grid Signals")
st.sidebar.caption("Nordic/Baltic power forecasts · historical demo")
try:
    manifest = load_manifest()
except SnapshotError:
    st.title("Grid Signals")
    st.error("Market explorer unavailable")
    st.write("The exported research data is unavailable. Please try again later.")
    st.stop()
st.session_state.explorer_manifest = manifest

navigation = {
    "Forecasts": [
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
pages = st.navigation(navigation)

# Keep shared values when a page does not render the corresponding widget.
# Streamlit otherwise clears widget state when that control leaves the page.
for key in ("selected_zone", "delivery_date", "selected_target", "selected_model"):
    if key in st.session_state:
        st.session_state[key] = st.session_state[key]
if "pending_zone" in st.session_state:
    st.session_state.selected_zone = st.session_state.pop("pending_zone")
if "pending_date" in st.session_state:
    st.session_state.delivery_date = st.session_state.pop("pending_date")
if "selected_zone" not in st.session_state:
    st.session_state.selected_zone = "SE3"
if "selected_target" not in st.session_state:
    st.session_state.selected_target = "wind_onshore"

st.title(
    {
        "Market explorer": "Market explorer",
        "Performance": "Evidence behind each model",
        "European coverage": "One market at a time",
        "Models & data": "What goes into the forecast",
    }[pages.title]
)
show_selection = pages.title != "European coverage"
if show_selection:
    selection = st.container(border=True)
    with selection:
        market_column, target_column, model_column = st.columns([3, 2, 3])
        market_column.selectbox(
            "Market area",
            [m.code for m in MARKETS],
            format_func=lambda code: f"{code.replace('_', '-')} · {BY_CODE[code].name}",
            key="selected_zone",
        )
        target_column.selectbox(
            "Forecast target",
            list(TARGETS),
            format_func=TARGETS.get,
            key="selected_target",
        )
zone = st.session_state.selected_zone
info = manifest["zones"].get(zone, {})
if "delivery_date" not in st.session_state:
    initial = (
        suggested_backtest_day(info)
        or (info.get("dates") or [manifest["exported_at"][:10]])[-1]
    )
    st.session_state.delivery_date = date.fromisoformat(initial)
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
if show_selection:
    model_column.selectbox(
        "Headline model" if pages.title == "Performance" else "Model",
        models or [None],
        format_func=lambda model: (
            model_name(model) if model else "No custom model in this area"
        ),
        key="selected_model",
        disabled=not models,
        help=(
            "Select the model for headline metrics. Choose comparison models below."
            if pages.title == "Performance"
            else None
        ),
    )
    if pages.title == "Market explorer":
        with selection:
            date_column, shortcuts = st.columns([1, 2])
            date_column.date_input(
                "Delivery date",
                key="delivery_date",
                help="Local market date. Missing series are shown explicitly.",
            )
            with shortcuts:
                if info.get("dates"):
                    st.caption(f"Archive: {info['dates'][0]} → {info['dates'][-1]}")
                latest, backtest = st.columns(2)
                if info.get("dates") and latest.button(
                    "Latest forecast / data", width="stretch"
                ):
                    st.session_state.pending_date = date.fromisoformat(
                        info["dates"][-1]
                    )
                    st.rerun()
                joint_day = suggested_backtest_day(info)
                if joint_day and backtest.button(
                    "Latest joint backtest", width="stretch"
                ):
                    st.session_state.pending_date = date.fromisoformat(joint_day)
                    st.rerun()
st.sidebar.divider()
st.sidebar.caption(
    f"Data bundle: {manifest['exported_at'][:10]} · historical replay + publication archive"
)
st.sidebar.markdown("[Source code](https://github.com/kaarelkivisalu/grid-signals)")
pages.run()
