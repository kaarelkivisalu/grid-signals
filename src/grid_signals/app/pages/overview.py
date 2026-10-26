"""A short portfolio introduction with a populated SE3 comparison."""

import pandas as pd
import streamlit as st

from grid_signals.app.explorer_charts import forecast_chart
from grid_signals.app.explorer_data import choose_curve
from grid_signals.app.markets import SELECTED_MODELS
from grid_signals.app.presentation import evaluated_forecasts, final_scores

manifest = st.session_state.explorer_manifest
st.title("Electricity forecasts")
st.write(
    "Day-ahead wind, solar and electricity-price forecasts. Start with SE3 wind, then explore the models and their results."
)
wind = evaluated_forecasts(manifest, "SE3")
wind = wind[(wind.target == "wind_onshore") & (wind.split == "Final holdout")]
if wind.empty:
    st.info(
        "The SE3 comparison is unavailable in this result bundle. Explore another product using the navigation."
    )
    st.stop()
day = wind.delivery_date.max()
rows = choose_curve(wind, "wind_onshore", day, "hourly_repeated")
reference = choose_curve(wind, "wind_onshore", day, "physical_power_curve")
st.subheader("SE3 · Onshore wind")
st.caption(f"Historical comparison · delivery {day} · Sweden, Central")
st.plotly_chart(
    forecast_chart(rows, "Europe/Stockholm", "wind_onshore", reference),
    width="stretch",
    key="featured_forecast",
)
st.caption(
    "Forecast and 80% prediction range against actual generation and a physical reference. Hourly forecasts are repeated over quarter-hours."
)
with st.container(horizontal=True):
    st.page_link("pages/wind.py", label="Explore wind")
    st.page_link("pages/solar.py", label="Explore solar")
    st.page_link("pages/price.py", label="Explore prices")
st.subheader("What has been evaluated")
summary = []
for zone, target, label in (
    ("SE3", "wind_onshore", "Onshore wind"),
    ("DE_LU", "solar", "Solar"),
    ("DE_LU", "price", "Spot prices"),
):
    scores = final_scores(manifest, zone, target)
    selected = scores[scores.model == SELECTED_MODELS[target]]
    if selected.empty:
        continue
    item = selected.iloc[0]
    unit = "EUR/MWh" if target == "price" else "% of capacity"
    summary.append(
        {
            "Product": label,
            "Market": zone.replace("_", "-"),
            "Average error": f"{item.MAE:.2f} {unit}",
            "Scored days": int(item.Days),
        }
    )
st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")
st.caption(
    "Final evaluation, separate from development. Error units differ across products; these rows are not a ranking. Saved results do not imply a reliable daily service."
)
with st.container(horizontal=True):
    st.page_link("pages/performance.py", label="See the evidence")
    st.page_link("pages/methods.py", label="Understand the inputs")
with st.expander("Additional case study"):
    st.page_link("pages/load.py", label="German electricity demand")
    st.write(
        "A supporting load-forecast study and a test of whether its predictions improve price forecasting."
    )
