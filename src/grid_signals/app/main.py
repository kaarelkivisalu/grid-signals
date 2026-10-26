"""Grid Signals: electricity forecasts, fundamentals and model evidence."""

from datetime import date

import streamlit as st

from grid_signals.app.explorer_data import load_manifest
from grid_signals.app.markets import SDAC_MARKETS
from grid_signals.app.snapshot import SnapshotError

st.set_page_config(page_title="Grid Signals · Electricity forecasts", layout="wide")
st.markdown(
    """<style>
    .stApp { background: #f8faf9; }
    .block-container { max-width: 1320px; padding-top: 2.8rem; }
    h1, h2, h3 { color: #183c3b; letter-spacing: -0.025em; }
    h1 { font-size: 2.6rem; }
    [data-testid="stSidebar"] { background: #edf3f0; }
    .st-key-sidebar-navigation [class*="st-key-navigation-"] { gap: .375rem; }
    .st-key-navigation-1, .st-key-navigation-2 {
        border-top: 1px solid #c6d4ce; padding-top: 1rem;
    }
    .st-key-sidebar-navigation [data-testid="stElementContainer"]:has(> [data-testid="stPageLink"]) {
        margin: 0;
    }
    .st-key-sidebar-navigation [data-testid="stPageLink"] > div {
        height: auto; min-height: 3rem;
    }
    .st-key-sidebar-navigation [data-testid="stPageLink-NavLink"] {
        box-sizing: border-box; min-height: 3rem; margin: 0;
        padding: .5rem .75rem; border-radius: 6px;
    }
    .st-key-sidebar-navigation [data-testid="stPageLink"] p {
        font-size: 1.125rem; line-height: 1.5;
    }
    [data-testid="stMetricValue"] { color: #183c3b; }
    [data-testid="stMetricLabel"] { color: #536963; }
    [data-testid="stCaptionContainer"] { opacity: 1; }
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p { color: #536963; }
    .github-link { display: inline-flex; align-items: center; gap: .55rem;
        color: #183c3b; text-decoration: none; padding: .6rem 0; }
    .github-link:hover { text-decoration: underline; text-underline-offset: .2em; }
    .github-link:focus-visible { outline: 2px solid #147d77; outline-offset: 4px; }
    ::selection { background: #c5e5dd; color: #183c3b; }
    </style>""",
    unsafe_allow_html=True,
)
try:
    st.session_state.explorer_manifest = load_manifest()
except SnapshotError:
    st.title("Grid Signals")
    st.error("Forecast results unavailable")
    st.write("The saved results could not be loaded. Please try again later.")
    st.stop()

# Keep choices when navigating to a page that does not use those widgets.
for key in ("selected_zone", "delivery_date", "selected_target", "selected_model"):
    if key in st.session_state:
        st.session_state[key] = st.session_state[key]
# Map and availability links carry their area into a fresh page request.
linked_area = st.query_params.get("area")
if linked_area in SDAC_MARKETS:
    st.session_state.selected_zone = linked_area
    st.session_state.selected_model = None
    del st.query_params["area"]
st.session_state.setdefault("selected_zone", "SE3")
st.session_state.setdefault("selected_target", "wind_onshore")
st.session_state.setdefault("selected_model", "hourly_repeated")
st.session_state.setdefault("delivery_date", date(2026, 9, 19))

link_groups = (
    (("overview", "Overview"), ("map", "Map")),
    (("price", "Prices"), ("wind", "Wind"), ("solar", "Solar")),
    (("methods", "Models & data"), ("performance", "Performance")),
)
links = [link for group in link_groups for link in group]
pages = st.navigation(
    [
        st.Page(f"pages/{path}.py", title=label, default=path == "overview")
        for path, label in links
    ]
    + [st.Page("pages/load.py", title="Load case study")],
    position="hidden",
)
with st.sidebar:
    st.title("Grid Signals")
    st.caption("Nordic/Baltic electricity")
    with st.container(gap="small", key="sidebar-navigation"):
        for index, group in enumerate(link_groups):
            with st.container(gap="small", key=f"navigation-{index}"):
                for path, label in group:
                    st.page_link(f"pages/{path}.py", label=label, width="stretch")
    st.divider()
    st.markdown(
        '<a class="github-link" href="https://github.com/kaarelkivisalu/grid-signals" '
        'target="_blank" rel="noopener noreferrer">'
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M12 .5a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.23'
        "c-3.34.73-4.04-1.42-4.04-1.42-.55-1.39-1.33-1.76-1.33-1.76"
        "-1.09-.75.08-.73.08-.73 1.21.08 1.85 1.24 1.85 1.24"
        "1.07 1.83 2.81 1.3 3.49.99.11-.78.42-1.3.76-1.6"
        "-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22"
        "-.12-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23"
        "a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23"
        ".66 1.66.24 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22"
        "0 4.61-2.81 5.63-5.49 5.93.43.37.81 1.1.81 2.22v3.29"
        'c0 .32.22.7.83.58A12 12 0 0 0 12 .5Z"/></svg>Source code</a>',
        unsafe_allow_html=True,
    )
pages.run()
