"""Transparent, filterable metrics on matched original backtest observations."""

from datetime import date

import streamlit as st

from grid_signals.app.explorer_charts import diagnostic_chart
from grid_signals.app.explorer_data import (
    GROUPS,
    SCORED_SPLITS,
    grouped_scores,
    matched_rows,
    read_market,
)
from grid_signals.app.markets import BY_CODE, TARGETS
from grid_signals.app.model_catalogue import model_name
from grid_signals.app.snapshot import SnapshotError

zone = st.session_state.selected_zone
target = st.session_state.selected_target
market = BY_CODE[zone]
st.caption("GRID SIGNALS / PERFORMANCE")
st.title("Evidence behind each model")
st.write(
    f"**{market.name} · {TARGETS[target]}** · grouped scores from original evaluated intervals"
)
try:
    forecasts = read_market(st.session_state.explorer_manifest, zone, "forecast")
except SnapshotError as exc:
    st.error(str(exc))
    st.stop()
if forecasts.empty:
    st.info(
        "No model has been backtested in this market yet. Bundled observations do not imply forecast skill."
    )
    st.stop()
frame = forecasts[(forecasts.target == target) & forecasts.split.isin(SCORED_SPLITS)]
if frame.empty:
    st.info(
        "No scored backtest exists for this market and target. Select another target or area."
    )
    st.stop()
scopes = [split for split in SCORED_SPLITS if split in frame.split.unique()]
left, right = st.columns([2, 1])
selected_scope = left.radio(
    "Evaluation window", scopes, horizontal=True, key=f"scope_{zone}_{target}"
)
frame = frame[frame.split == selected_scope]
group = right.selectbox("Group scores by", GROUPS, key="score_group")
start, stop = frame.delivery_date.min(), frame.delivery_date.max()
limits = (date.fromisoformat(start), date.fromisoformat(stop))
range_key = f"score_range_{zone}_{target}_{selected_scope}"
explorer_day = st.session_state.delivery_date
if st.button(
    "Use explorer delivery date", disabled=not limits[0] <= explorer_day <= limits[1]
):
    st.session_state[range_key] = (explorer_day, explorer_day)
chosen_dates = st.date_input(
    "Scored delivery range",
    value=limits,
    min_value=limits[0],
    max_value=limits[1],
    key=range_key,
)
if len(chosen_dates) != 2:
    st.info("Choose both the start and end of the scored range.")
    st.stop()
frame = frame[
    frame.delivery_date.between(
        chosen_dates[0].isoformat(), chosen_dates[1].isoformat()
    )
]
if frame.empty:
    st.info(
        "No scored predictions in this date range. Missing delivery days are excluded, not filled."
    )
    st.stop()
models = sorted(frame.model.unique(), key=model_name)
selected = st.multiselect(
    "Compare models · matched intervals",
    models,
    default=models,
    format_func=model_name,
    key=f"score_models_{zone}_{target}_{selected_scope}",
)
if not selected:
    st.info("Select at least one model to calculate the comparison.")
    st.stop()
renewable = target in {"solar", "wind_onshore"}
capacity = (
    st.toggle("Normalise errors by installed capacity", value=True)
    if renewable
    else False
)
rows = matched_rows(frame, selected)
if rows.empty:
    st.info("No common eligible intervals remain for these models and dates.")
    st.stop()
unit = "% capacity" if capacity else "EUR/MWh" if target == "price" else "MW"
scores = grouped_scores(rows, group, market.timezone, capacity=capacity)
overall = grouped_scores(rows, "Overall", market.timezone, capacity=capacity)
selected_model = st.session_state.selected_model
headline = overall[overall.model == selected_model]
if headline.empty:
    headline = overall.sort_values("CRPS").head(1)
headline = headline.iloc[0]
st.caption(
    f"Headline: {model_name(headline.model)} · {selected_scope} · {chosen_dates[0]} to {chosen_dates[1]}"
)
cols = st.columns(4)
cols[0].metric(f"MAE · {unit}", f"{headline.MAE:,.2f}")
cols[1].metric(f"CRPS · {unit}", f"{headline.CRPS:,.2f}")
cols[2].metric("80% interval coverage", f"{headline.Coverage80:.1f}%")
cols[3].metric(
    "Delivery days / intervals", f"{int(headline.Days)} / {int(headline.Intervals):,}"
)
if selected_scope == "Final holdout":
    requested = {"wind_onshore": 184, "solar": 184, "price": 44, "load": 44}[target]
    st.caption(
        f"Frozen final evaluation · full release requests {requested} delivery days. The table reflects the selected date range and common model intervals; missing days are never filled. Research models were not tuned on this window."
    )
    if target == "wind_onshore":
        st.caption(
            "Wind release: 182/184 complete days; June 24 and September 3 are missing."
        )
    elif target == "price":
        st.caption(
            "Price release: 42/44 complete days; September 13 lacks genuine quarter-hours and September 20 lacks an eligible weekly lag."
        )
else:
    st.warning(
        "Development results supported model selection. They are not an independent test. Model rankings across different target windows are not directly comparable."
    )
st.caption(
    "All selected models use identical eligible timestamps and original targets. MAE/CRPS and bias are interval-weighted. Positive bias always means forecast - actual (overprediction)."
    + (
        " Solar scores include daylight only (solar elevation >5°)."
        if target == "solar"
        else ""
    )
)
if group == "Market quarter":
    st.caption(
        "Q001 is the first 15-minute interval after local midnight. DST days have 92 or 100 intervals; both repeated autumn hours remain distinct. This is interval order, not clock-hour averaging."
    )
if group == "Season":
    st.caption(
        "Meteorological seasons: Dec-Feb winter (December belongs to the following season year), Mar-May spring, Jun-Aug summer, Sep-Nov autumn."
    )
display = scores.rename(
    columns={
        "split": "Evaluation",
        "model": "Model",
        "Coverage80": "80% coverage (%)",
        "Coverage90": "90% coverage (%)",
    }
)
display["Model"] = display.Model.map(model_name)
display = display.rename(
    columns={name: f"{name} ({unit})" for name in ["MAE", "CRPS", "Bias"]}
)
st.dataframe(display.round(3), hide_index=True, width="stretch")
metric = st.selectbox(
    "Plot metric",
    ["MAE", "CRPS", "Bias", "Coverage80", "Coverage90"],
    format_func=lambda key: {
        "Coverage80": "80% coverage (%)",
        "Coverage90": "90% coverage (%)",
    }.get(key, f"{key} ({unit})"),
)
st.plotly_chart(
    diagnostic_chart(scores, metric), width="stretch", key="grouped_performance"
)
st.download_button(
    "Download grouped metrics · CSV",
    display.to_csv(index=False).encode(),
    file_name=f"{zone}-{target}-{group.lower().replace(' ', '-')}-metrics.csv",
    mime="text/csv",
)
with st.expander("Dates scored & missing days"):
    st.write(
        f"{rows.delivery_date.nunique()} scored dates after matching; archive window {start} to {stop}."
    )
    st.write(", ".join(sorted(rows.delivery_date.unique())))
with st.expander("What the scores measure"):
    st.write(
        "MAE measures absolute median error. CRPS measures the full predictive distribution using all 19 original quantiles. Lower is better for both. Coverage measures observations inside an interval: the nominal 80% band should cover about 80%, but aggregate coverage can hide seasonal failures."
    )
    st.write(
        "Capacity-normalised renewable scores divide each interval by its installed capacity before aggregation. They do not divide by actual output. No commercial vendor forecast is included in this leaderboard; historical public curves without verified issue timestamps are excluded."
    )
