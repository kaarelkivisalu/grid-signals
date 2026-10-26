"""A short portfolio introduction with a populated SE3 comparison."""

import pandas as pd
import streamlit as st

from grid_signals.app.explorer_charts import forecast_chart
from grid_signals.app.explorer_data import choose_curve
from grid_signals.app.markets import SELECTED_MODELS
from grid_signals.app.presentation import (
    evaluated_forecasts,
    final_scores,
    page_heading,
)

manifest = st.session_state.explorer_manifest
detailed = page_heading("Electricity forecasts", "overview")
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
st.caption(f"SE3 onshore wind · {day} · Final evaluation")
st.plotly_chart(
    forecast_chart(
        rows, "Europe/Stockholm", "wind_onshore", reference, show_error=detailed
    ),
    width="stretch",
    key="featured_forecast",
    config={"displayModeBar": detailed},
)
st.subheader("Final results")
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
st.table(pd.DataFrame(summary).set_index("Product"), border="horizontal")
if detailed:
    st.write(
        "Final evaluation is separate from development. Products use different units and periods. These saved results do not establish reliable daily publication."
    )
    st.caption(
        "Wind uses hourly-trained distributions repeated over quarter-hours; the shaded range covers the 10th to 90th quantile."
    )
    st.page_link("pages/load.py", label="German electricity demand case study")
