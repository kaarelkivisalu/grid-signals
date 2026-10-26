"""Matched model results and visible diagnostic controls."""

from datetime import date

import streamlit as st

from grid_signals.app.explorer_charts import diagnostic_chart
from grid_signals.app.explorer_data import (
    GROUPS,
    SCORED_SPLITS,
    grouped_scores,
    matched_rows,
)
from grid_signals.app.markets import BY_CODE
from grid_signals.app.model_catalogue import model_name
from grid_signals.app.presentation import (
    evaluated_forecasts,
    market_choices,
    target_choices,
)

manifest = st.session_state.explorer_manifest
st.title("Performance")
target = target_choices()
zone = market_choices(manifest, target)
market = BY_CODE[zone]
forecasts = evaluated_forecasts(manifest, zone)
frame = forecasts[(forecasts.target == target) & forecasts.split.isin(SCORED_SPLITS)]
scopes = [split for split in SCORED_SPLITS if (frame.split == split).any()]
settings = st.session_state.setdefault(f"comparison_{zone}_{target}", {})
scope = settings.get("scope", scopes[0])
if scope not in scopes:
    scope = scopes[0]
evaluation_column, period_column, comparison_column = st.columns([1, 2, 2])
scope = evaluation_column.selectbox(
    "Evaluation",
    scopes,
    index=scopes.index(scope),
    key=f"scope_{zone}_{target}",
    format_func=lambda value: (
        "Final evaluation" if value == "Final holdout" else "Development"
    ),
)
frame = frame[frame.split == scope]
start, stop = frame.delivery_date.min(), frame.delivery_date.max()
limits = (date.fromisoformat(start), date.fromisoformat(stop))
selected_dates = settings.get(f"dates_{scope}", limits)
models = sorted(frame.model.unique(), key=model_name)
selected = settings.get(f"models_{scope}", models)
capacity = settings.get("capacity", target in {"solar", "wind_onshore"})
group = settings.get("group", "Overall")
selected_dates = period_column.date_input(
    "Scored delivery range",
    value=selected_dates,
    min_value=limits[0],
    max_value=limits[1],
    key=f"score_range_{zone}_{target}_{scope}",
)
selected = comparison_column.multiselect(
    "Compare models",
    models,
    default=selected,
    format_func=model_name,
    key=f"score_models_{zone}_{target}_{scope}",
)
if target in {"solar", "wind_onshore"}:
    capacity = st.checkbox(
        "Normalise by installed capacity",
        value=capacity,
        key=f"capacity_{zone}_{target}",
    )
settings.update(
    {
        "scope": scope,
        f"dates_{scope}": selected_dates,
        f"models_{scope}": selected,
        "capacity": capacity,
        "group": group,
    }
)
if len(selected_dates) != 2:
    st.info("Choose both dates.")
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
    st.info("Select a model to compare.")
    st.stop()
rows = matched_rows(frame, selected)
if rows.empty:
    st.info("No common eligible intervals remain for these models and dates.")
    st.stop()
unit = "% capacity" if capacity else "EUR/MWh" if target == "price" else "MW"
overall = grouped_scores(rows, "Overall", market.timezone, capacity=capacity)
label = "Final evaluation" if scope == "Final holdout" else "Development"
st.caption(
    f"{zone.replace('_', '-')} · {label} · {rows.delivery_date.nunique()} days · {selected_dates[0]:%d %b %Y} to {selected_dates[1]:%d %b %Y}"
)
table = overall[["model", "MAE", "Coverage80"]].sort_values("MAE").copy()
table["model"] = table.model.map(model_name)
table = table.rename(
    columns={
        "model": "Model",
        "MAE": f"Average error ({unit})",
        "Coverage80": "80% range coverage (%)",
    }
)
st.table(
    table.set_index("Model").style.format(
        {
            f"Average error ({unit})": "{:.2f}",
            "80% range coverage (%)": "{:.1f}",
        }
    ),
    border="horizontal",
)
group_column, metric_column = st.columns(2)
group = group_column.selectbox(
    "Group scores by", GROUPS, index=GROUPS.index(group), key="score_group"
)
settings["group"] = group
scores = grouped_scores(rows, group, market.timezone, capacity=capacity)
metric = metric_column.selectbox(
    "Diagnostic",
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
if group != "Overall":
    st.dataframe(details.round(3), hide_index=True, width="stretch")
st.download_button(
    "Download metrics · CSV",
    details.to_csv(index=False).encode(),
    file_name=f"{zone}-{target}-{group.lower().replace(' ', '-')}-metrics.csv",
    mime="text/csv",
)
st.subheader("Scoring")
st.write(
    "MAE measures median error. CRPS scores all 19 original quantiles. Positive bias means overprediction. All models use the same eligible timestamps and original targets; scores are interval-weighted."
)
st.write(
    "Solar scores use daylight only. Renewable errors can be normalised by installed capacity. Final evaluation is separate from development model selection; replays do not prove on-time publication."
)
if scope == "Development":
    st.write("This development window was used for model selection.")
elif target == "wind_onshore":
    st.write("Full release: 182 of 184 days. June 24 and September 3 are missing.")
elif target == "price":
    st.write(
        "Full release: 42 of 44 days. Missing quarter-hours and an unavailable weekly lag exclude two days."
    )
st.caption(
    "Market quarters follow elapsed order after local midnight. DST days retain 92 or 100 intervals; winter groups December with the following January and February."
)
