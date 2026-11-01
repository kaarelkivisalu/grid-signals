"""Market-area boundaries and a full availability matrix."""

import pandas as pd
import streamlit as st

from grid_signals.app.explorer_charts import coverage_map
from grid_signals.app.markets import MARKET_GROUPS

manifest = st.session_state.explorer_manifest
st.title("Map")
with st.container(gap="small"):
    st.markdown(coverage_map(manifest), unsafe_allow_html=True)
    st.markdown(
        "Bidding-zone boundaries from [entsoe-py](https://github.com/EnergieID/entsoe-py/tree/master/entsoe/geo), "
        "simplified for display."
    )
st.divider()
st.subheader("Availability")
rows = []


def group_priority(group):
    areas = [manifest["zones"].get(code, {}) for code in group[1]]
    return (
        not any(area.get("targets") for area in areas),
        not any(area.get("observations") for area in areas),
    )


for group, codes in sorted(MARKET_GROUPS.items(), key=group_priority):
    for code in codes:
        info = manifest["zones"].get(code, {})
        targets = info.get("targets", {})
        observations = info.get("observations", {})
        rows.append(
            {
                "Region": group,
                "Area": f"[{code.replace('_', '-')}](/?area={code})",
                **{
                    label: f"[Forecast](/{ {'wind_onshore': 'wind', 'solar': 'solar', 'load': 'load', 'price': 'price'}[target] }?area={code})"
                    if target in targets
                    else f"[Data](/?area={code}#{'electricity-price' if target == 'price' else 'fundamentals'})"
                    if target in observations
                    else "—"
                    for target, label in (
                        ("wind_onshore", "Wind"),
                        ("solar", "Solar"),
                        ("load", "Load"),
                        ("price", "Prices"),
                    )
                },
            }
        )


def status_style(value: str) -> str:
    value = (
        "Forecast"
        if value.startswith("[Forecast]")
        else "Data"
        if value.startswith("[Data]")
        else value
    )
    return {
        "Forecast": "background-color: #c8e5d8; color: #174e3d; font-weight: 600",
        "Data": "background-color: #deebf3; color: #244d67",
        "—": "background-color: #edf0ef; color: #536963",
    }.get(value, "")


st.markdown(
    """<style>
    .st-key-market-matrix table { width: 100%; table-layout: fixed; }
    .st-key-market-matrix a { color: inherit; text-underline-offset: .15em; }
    .st-key-market-matrix th, .st-key-market-matrix td {
        padding: .2rem .35rem; overflow-wrap: anywhere;
    }
    @media (max-width: 600px) {
        .st-key-market-matrix th, .st-key-market-matrix td,
        .st-key-market-matrix th p, .st-key-market-matrix td p { font-size: .75rem; }
    }
    </style>""",
    unsafe_allow_html=True,
)
matrix = pd.DataFrame(rows).drop(columns="Region").set_index("Area")
with st.container(key="market-matrix", width=640):
    st.table(matrix.style.map(status_style), border="horizontal")
