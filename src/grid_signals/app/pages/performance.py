"""A readable matched comparison, with optional period and diagnostic controls."""

from datetime import date

import streamlit as st

from grid_signals.app.explorer_charts import diagnostic_chart
from grid_signals.app.explorer_data import (
    GROUPS,
    SCORED_SPLITS,
    grouped_scores,
    matched_rows,
)
from grid_signals.app.markets import BY_CODE, SELECTED_MODELS, TARGETS
from grid_signals.app.model_catalogue import model_name
from grid_signals.app.presentation import (
    evaluated_forecasts,
    market_choices,
    target_choices,
)

manifest = st.session_state.explorer_manifest
st.title("How the models compare")
st.write(
    "Compare each forecast with simpler alternatives on the same observations. Lower error is better."
)
target = target_choices()
zone = market_choices(manifest, target)
market = BY_CODE[zone]
forecasts = evaluated_forecasts(manifest, zone)
frame = forecasts[(forecasts.target == target) & forecasts.split.isin(SCORED_SPLITS)]
scopes = [split for split in SCORED_SPLITS if (frame.split == split).any()]
scope = (
    st.segmented_control(
        "Evaluation",
        scopes,
        default=scopes[0],
        key=f"scope_{zone}_{target}",
        format_func=lambda value: (
            "Final evaluation" if value == "Final holdout" else "Development"
        ),
    )
    or scopes[0]
)
frame = frame[frame.split == scope]
start, stop = frame.delivery_date.min(), frame.delivery_date.max()
limits = (date.fromisoformat(start), date.fromisoformat(stop))
summary = st.container()
with st.expander("Adjust period & comparison"):
    selected_dates = st.date_input(
        "Scored delivery range",
        value=limits,
        min_value=limits[0],
        max_value=limits[1],
        key=f"score_range_{zone}_{target}_{scope}",
    )
    models = sorted(frame.model.unique(), key=model_name)
    selected = st.multiselect(
        "Compare models",
        models,
        default=models,
        format_func=model_name,
        key=f"score_models_{zone}_{target}_{scope}",
    )
    renewable = target in {"solar", "wind_onshore"}
    capacity = (
        st.toggle("Show errors as % of installed capacity", value=True)
        if renewable
        else False
    )
    group = st.selectbox("Group scores by", GROUPS, key="score_group")
if len(selected_dates) != 2:
    st.info("Choose both the start and end of the scored range.")
    st.stop()
frame = frame[
    frame.delivery_date.between(
        selected_dates[0].isoformat(), selected_dates[1].isoformat()
    )
]
if frame.empty:
    st.info("No scored predictions in this date range. Missing days are not filled.")
    st.stop()
if not selected:
    st.info("Select at least one model to calculate the comparison.")
    st.stop()
rows = matched_rows(frame, selected)
if rows.empty:
    st.info("No common eligible intervals remain for these models and dates.")
    st.stop()
unit = "% capacity" if capacity else "EUR/MWh" if target == "price" else "MW"
overall = grouped_scores(rows, "Overall", market.timezone, capacity=capacity)
preferred = SELECTED_MODELS[target]
headline = overall[overall.model == preferred]
headline = (headline if not headline.empty else overall.sort_values("CRPS")).iloc[0]
scores = grouped_scores(rows, group, market.timezone, capacity=capacity)
with summary:
    st.subheader(f"{zone.replace('_', '-')} · {TARGETS[target]}")
    st.caption(
        f"{selected_dates[0]} to {selected_dates[1]} · {int(headline.Days)} scored days · {'final evaluation' if scope == 'Final holdout' else 'development'}"
    )
    left, right = st.columns(2)
    left.metric(f"Average error · {unit}", f"{headline.MAE:,.2f}")
    right.metric("80% range: actual coverage", f"{headline.Coverage80:.1f}%")
    st.caption(
        f"{model_name(headline.model)}. Average error measures the distance between the median forecast and actuals. An 80% range aims to contain actuals about 80% of the time."
    )
    table = overall[["model", "MAE", "CRPS", "Coverage80", "Days"]].copy()
    table["model"] = table.model.map(model_name)
    table = table.rename(
        columns={
            "model": "Model",
            "MAE": f"Average error ({unit})",
            "CRPS": f"Distribution error ({unit})",
            "Coverage80": "80% range coverage (%)",
            "Days": "Days",
        }
    )
    st.dataframe(table.round(3), hide_index=True, width="stretch")
    if scope == "Development":
        st.warning(
            "Development results helped select the model. Use final evaluation for independent evidence."
        )
    elif target == "wind_onshore":
        st.caption(
            "Full wind release: 182 of 184 complete days. June 24 and September 3 are missing."
        )
    elif target == "price":
        st.caption(
            "Full price release: 42 of 44 complete days. Missing quarter-hours and an unavailable weekly lag exclude two days."
        )
with st.expander("Diagnostics, definitions & downloads"):
    metric = st.selectbox(
        "Plot metric",
        ["MAE", "CRPS", "Bias", "Coverage80", "Coverage90"],
        format_func=lambda value: {
            "MAE": "Average error",
            "CRPS": "Distribution error",
            "Coverage80": "80% range coverage",
            "Coverage90": "90% range coverage",
        }.get(value, value),
    )
    st.plotly_chart(
        diagnostic_chart(scores, metric), width="stretch", key="grouped_performance"
    )
    details = scores.copy()
    details["model"] = details.model.map(model_name)
    st.dataframe(details.round(3), hide_index=True, width="stretch")
    st.write(
        "MAE is average absolute median error. CRPS scores the whole predictive distribution using all 19 original quantiles. Bias is forecast minus actual; positive values mean overprediction."
    )
    st.write(
        "Every selected model is scored on identical eligible timestamps and original targets. Scores are interval-weighted. Renewable errors can be divided by installed capacity; solar scores include daylight only."
    )
    st.write(
        "Final evaluations were kept separate from development model selection. Historical replays do not prove on-time publication, and original source resolution limits what can be claimed about quarter-hour skill."
    )
    st.caption(
        "Q001 is the first quarter-hour after local midnight. DST days retain 92 or 100 distinct intervals. Winter groups December with the following January and February."
    )
    st.download_button(
        "Download grouped metrics · CSV",
        details.to_csv(index=False).encode(),
        file_name=f"{zone}-{target}-{group.lower().replace(' ', '-')}-metrics.csv",
        mime="text/csv",
    )
    st.write("Scored delivery dates")
    st.write(", ".join(sorted(rows.delivery_date.unique())))
