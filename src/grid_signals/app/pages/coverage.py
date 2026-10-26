"""A focused country map with truthful zone and target availability."""

import pandas as pd
import streamlit as st

from grid_signals.app.explorer_charts import coverage_map
from grid_signals.app.markets import BY_CODE, PORTFOLIO_MARKETS

manifest = st.session_state.explorer_manifest
st.title("Where the data reaches")
st.write("Nordic/Baltic markets, with Germany-Luxembourg as a supporting case study.")
st.plotly_chart(
    coverage_map(manifest),
    width="stretch",
    key="regional_coverage",
    config={"scrollZoom": False, "displayModeBar": False},
)
st.caption(
    "Country colour means at least one zone has that status. Sweden's evaluated forecast is SE3 onshore wind; the other Swedish zones are not yet evaluated. Colours do not claim full country or daily publication coverage."
)
st.subheader("Forecast availability by market")
rows = []
for code in PORTFOLIO_MARKETS:
    info = manifest["zones"].get(code, {})
    targets = info.get("targets", {})
    rows.append(
        {
            "Market": code.replace("_", "-"),
            "Area": BY_CODE[code].name,
            "Observations": "Available" if info.get("observations") else "Not imported",
            **{
                label: "Evaluated" if target in targets else "Not yet evaluated"
                for target, label in (
                    ("wind_onshore", "Wind"),
                    ("solar", "Solar"),
                    ("price", "Prices"),
                )
            },
        }
    )
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
with st.expander("Scope & map source"):
    st.write(
        "The destination is evaluated wind, solar and spot-price forecasts across SE1-SE4, NO1-NO5, DK1-DK2, FI, EE, LV and LT. SE3 leads; SE4 follows after daily SE3 delivery is established. Offshore wind follows separately."
    )
    st.markdown(
        "[Natural Earth country outlines](https://www.naturalearthdata.com/about/terms-of-use/) are public domain. Country borders are geographic context, not bidding-zone boundaries. The map uses local geometry and needs no map service."
    )
