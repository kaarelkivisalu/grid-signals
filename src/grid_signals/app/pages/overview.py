"""One area's prices and combined fundamentals, with one forecast per product."""

import streamlit as st

from grid_signals.app.explorer_charts import overview_chart
from grid_signals.app.explorer_data import (
    SCORED_SPLITS,
    choose_curve,
    local_dates,
    market_day,
    read_market,
)
from grid_signals.app.presentation import delivery_day, market_choices
from grid_signals.app.publication import render as publication_record
from grid_signals.markets import BY_CODE, SELECTED_MODELS

manifest = st.session_state.explorer_manifest
st.title("Electricity markets")
publication_record(manifest)
zone = market_choices(manifest)
market = BY_CODE[zone]
observed = read_market(manifest, zone, "observation")
forecasts = read_market(manifest, zone, "forecast")
# Overview shows the chosen product models, never multiple alternatives or issues.
if not forecasts.empty:
    forecasts = forecasts[
        forecasts.split.isin(SCORED_SPLITS)
        & forecasts.model.eq(forecasts.target.map(SELECTED_MODELS))
    ]
if observed.empty and forecasts.empty:
    st.info(
        f"No saved data for {zone.replace('_', '-')} yet. Choose another area above."
    )
    st.stop()
days = (
    set(local_dates(observed.valid_time, market.timezone))
    if not observed.empty
    else set()
)
if not forecasts.empty:
    days.update(forecasts.delivery_date)
day = delivery_day(list(days), f"overview_day_{zone}")
frame = market_day(observed, day, market.timezone)
curves = {}
for target, model in SELECTED_MODELS.items():
    curve = choose_curve(forecasts, target, day, model)
    if curve.empty:
        continue
    curves[target] = curve
    # Original evaluation actuals remain available when observation imports end early.
    actual = curve.set_index("valid_time").actual.reindex(frame.index)
    frame[target] = frame[target].combine_first(actual) if target in frame else actual
for title, products, key in (
    ("Electricity price", ["price"], "overview_prices"),
    (
        "Fundamentals",
        ["wind_onshore", "wind_offshore", "solar", "load", "residual_load"],
        "overview_fundamentals",
    ),
):
    st.subheader(title)
    if not any(
        (product in frame and frame[product].notna().any()) or product in curves
        for product in products
    ):
        st.caption("No saved data for this area and date.")
    st.plotly_chart(
        overview_chart(frame, curves, market.timezone, products),
        width="stretch",
        key=key,
        config={"displayModeBar": False},
    )
