"""Market coverage and current capabilities, with an offline clickable map."""

import pandas as pd
import streamlit as st

from grid_signals.app.explorer_charts import coverage_map
from grid_signals.app.markets import MARKETS, SDAC_SOURCE, TARGETS

manifest = st.session_state.explorer_manifest
zone = st.session_state.selected_zone
st.write(
    "The destination is wind, solar and day-ahead spot-price forecasts across 15 Nordic/Baltic bidding zones: SE1-SE4, NO1-NO5, DK1-DK2, FI, EE, LV and LT. The wider European map provides context. Imported data, evaluated models and publication records are separate claims."
)
cols = st.columns(3)
cols[0].metric("Areas with bundled data", str(len(manifest["zones"])))
cols[1].metric(
    "Areas with custom models",
    str(sum(bool(info["targets"]) for info in manifest["zones"].values())),
)
cols[2].metric("SDAC zones in this registry", str(sum(m.sdac for m in MARKETS)))
selection = st.plotly_chart(
    coverage_map(manifest, zone),
    width="stretch",
    key="european_coverage",
    on_select="rerun",
    selection_mode="points",
    config={"scrollZoom": False, "displayModeBar": False},
)
if selection and selection.selection.points:
    code = selection.selection.points[-1].get("customdata")
    if code in {m.code for m in MARKETS} and code != zone:
        st.session_state.pending_zone = code
        st.rerun()
st.caption(
    "Select a marker to change the shared market. Anchors are approximate zone locations; country outlines are geographic context, not bidding-zone boundaries. Zoom to inspect the smaller zones. The map works without an external map service."
)
st.markdown(
    f"Membership reviewed 2026-10-15 against [ENTSO-E SDAC scope]({SDAC_SOURCE}). Ireland/Northern Ireland share SEM; Great Britain is outside SDAC. SDAC membership does not guarantee every dataset or its redistribution rights. [Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/) country outlines are public domain."
)
rows = []
for market in MARKETS:
    info = manifest["zones"].get(market.code, {})
    observations = info.get("observations", {})
    targets = info.get("targets", {})
    rows.append(
        {
            "Area": market.code.replace("_", "-"),
            "Market": market.name,
            "Map category": "Outside SDAC"
            if not market.sdac
            else "Project data / forecasts"
            if info
            else "SDAC · not yet imported",
            "Bundled observations": ", ".join(
                TARGETS.get(key, "Offshore wind") for key in observations
            )
            or "Not imported",
            "Custom models": ", ".join(TARGETS[key] for key in targets)
            or "None evaluated",
            "Data dates": f"{info['dates'][0]} → {info['dates'][-1]}"
            if info.get("dates")
            else "—",
        }
    )
show_all = st.toggle("Show areas without imported data", value=False)
st.dataframe(
    pd.DataFrame(
        rows
        if show_all
        else [row for row in rows if row["Map category"] == "Project data / forecasts"]
    ),
    hide_index=True,
    width="stretch",
)
st.subheader("Expansion priorities")
st.write(
    "Publish the historical demo with SE3 onshore wind first, then establish daily SE3 publication, transfer wind to SE4 and compare one deep-learning challenger. Extend onshore wind, solar and spot prices one zone and target at a time; offshore wind follows where applicable. German solar, load and price results remain supporting case studies."
)
st.caption(
    "Additional market data covers a bounded September-October 2026 preview. It supports exploration and data-quality assessment; no custom skill has been established in those areas."
)
