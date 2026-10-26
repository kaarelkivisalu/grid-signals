"""Explore one market/day with aligned fundamentals, prices and model evidence."""

import pandas as pd
import streamlit as st

from grid_signals.app.explorer_charts import (
    error_chart,
    forecast_chart,
    fundamentals_chart,
    price_relationship,
)
from grid_signals.app.explorer_data import choose_curve, market_day, read_market
from grid_signals.app.markets import BY_CODE, SELECTED_MODELS, TARGETS
from grid_signals.app.model_catalogue import CATALOGUE, model_name
from grid_signals.app.snapshot import SnapshotError

manifest = st.session_state.explorer_manifest
zone = st.session_state.selected_zone
market = BY_CODE[zone]
day = st.session_state.delivery_date.isoformat()
target = st.session_state.selected_target
model = st.session_state.selected_model
st.title(market.name)
st.write(
    f"**{zone.replace('_', '-')} · delivery {day}** · {market.timezone} · day-ahead forecasting"
)
st.write(
    "Nordic/Baltic day-ahead forecasting starts with SE3 wind. German solar, load and price case studies are available in the sidebar."
)
if zone not in manifest["zones"]:
    st.info(
        "This area is on the coverage map but has no data bundled yet. Select an area with project data to explore actual series and forecasts."
    )
    st.page_link(
        "pages/coverage.py", label="Explore European coverage", icon=":material/map:"
    )
    st.stop()
try:
    observed = read_market(manifest, zone, "observation")
    forecasts = read_market(manifest, zone, "forecast")
except SnapshotError as exc:
    st.error(str(exc))
    st.stop()
frame = market_day(observed, day, market.timezone)
curves = {
    key: choose_curve(forecasts, key, day, model if key == target else value)
    for key, value in SELECTED_MODELS.items()
}
st.caption(
    "Historical demo · saved forecasts and actuals. Replays do not prove on-time publication; daily updates are not yet an always-on service."
)
st.subheader(f"{TARGETS[target]} · forecast detail")
rows = curves.get(target, pd.DataFrame())
if rows.empty:
    available = (
        manifest["zones"][zone].get("targets", {}).get(target, {}).get("dates", [])
    )
    st.info(
        f"No {TARGETS[target].lower()} model output for {zone.replace('_', '-')} on {day}."
        + (
            f" Available forecast dates: {available[0]} to {available[-1]}, with gaps."
            if available
            else " This target has not been modelled in this area."
        )
    )
else:
    if rows.split.iloc[0] == "Published archive":
        all_rows = forecasts[
            (forecasts.target == target)
            & (forecasts.model == model)
            & (forecasts.delivery_date == day)
            & (forecasts.split == "Published archive")
        ]
        ids = all_rows.sort_values("published_at").forecast_id.unique().tolist()
        chosen = st.selectbox(
            "Forecast issue / revision",
            ids,
            index=len(ids) - 1,
            format_func=lambda key: (
                f"{all_rows[all_rows.forecast_id == key].published_at.iloc[0]} · {all_rows[all_rows.forecast_id == key].publication_status.iloc[0]} · {str(key)[:8]}"
            ),
        )
        rows = all_rows[all_rows.forecast_id == chosen].sort_values("valid_time")
        first = rows.iloc[0]
        st.info(
            f"Publication status: {first.publication_status}. Information cutoff {first.information_cutoff_at}; published {first.published_at}. This view does not count late forecasts as an on-time record."
        )
        if target in frame:
            rows = rows.copy()
            rows["actual"] = (
                frame[target].reindex(pd.DatetimeIndex(rows.valid_time)).to_numpy()
            )
    else:
        st.caption(
            f"{rows.split.iloc[0]} · {len(rows)} delivery intervals · information cutoff 09:00 UTC on the preceding day. Original 19-quantile scores are available in Performance."
        )
    others = [
        name
        for name in forecasts[
            (forecasts.target == target)
            & (forecasts.delivery_date == day)
            & (forecasts.split == rows.split.iloc[0])
        ].model.unique()
        if name != model
    ]
    comparison = st.selectbox(
        "Compare median with",
        [None, *others],
        index=(
            [None, *others].index("physical_power_curve")
            if "physical_power_curve" in others
            else 0
        ),
        format_func=lambda key: model_name(key) if key else "None",
    )
    reference = choose_curve(forecasts, target, day, comparison) if comparison else None
    st.plotly_chart(
        forecast_chart(rows, market.timezone, target, reference),
        width="stretch",
        key="forecast_detail",
    )
    if rows.actual.notna().any():
        st.plotly_chart(
            error_chart(rows, market.timezone, target),
            width="stretch",
            key="forecast_errors",
        )
        st.caption(
            "Positive error = overprediction. Solar performance scores use daylight only; this plot includes the whole delivery day."
        )
    if model in CATALOGUE:
        recipe, features, uncertainty, resolution, limits = CATALOGUE[model]
        with st.expander("Model & input features", expanded=True):
            st.write(f"**{model_name(model)}** · {recipe}")
            for feature in features:
                st.markdown(f"- {feature}")
            st.caption(f"{uncertainty} {resolution} {limits}")
    st.download_button(
        "Download this forecast · CSV",
        rows.to_csv(index=False).encode(),
        file_name=f"{zone}-{target}-{day}.csv",
        mime="text/csv",
    )

metrics = st.columns(3)
if "price" in frame and frame.price.notna().any():
    metrics[0].metric("Mean spot price", f"€{frame.price.mean():.2f}/MWh")
    metrics[1].metric("Lowest spot price", f"€{frame.price.min():.2f}/MWh")
else:
    metrics[0].metric("Spot observations", "Unavailable")
    metrics[1].metric("Delivery intervals", str(len(frame)))
if "residual_load" in frame and frame.residual_load.notna().any():
    metrics[2].metric(
        "Mean residual load", f"{frame.residual_load.mean() / 1000:.1f} GW"
    )
else:
    metrics[2].metric(
        "Forecast components", f"{sum(not rows.empty for rows in curves.values())} / 4"
    )

st.subheader("Fundamentals & spot price")
left, right = st.columns([3, 1])
selected_series = left.multiselect(
    "Power series",
    ["load", "solar", "wind_onshore", "wind_offshore", "residual_load"],
    default=["load", "solar", "wind_onshore", "wind_offshore", "residual_load"],
    format_func=lambda key: TARGETS.get(key, "Offshore wind"),
    key="power_series",
)
hourly = (
    right.segmented_control("Display interval", ["15 min", "Hourly"], default="15 min")
    == "Hourly"
)
show_forecasts = st.toggle("Overlay model medians", value=True)
st.plotly_chart(
    fundamentals_chart(
        frame,
        curves if show_forecasts else {},
        market.timezone,
        selected_series,
        hourly=hourly,
    ),
    width="stretch",
    key="fundamentals",
)
st.caption(
    "Solid = observations · dashed = model medians. Power is in GW; prices use a separate EUR/MWh axis. Hourly display uses complete four-quarter means; repeated source hours do not establish quarter-hour skill."
)
coverage = []
for key, label in [
    ("load", "Total load"),
    ("solar", "Solar"),
    ("wind_onshore", "Onshore wind"),
    ("wind_offshore", "Offshore wind"),
    ("residual_load", "Residual load"),
    ("price", "Spot price"),
]:
    count = int(frame[key].notna().sum()) if key in frame else 0
    curve = curves.get(key, pd.DataFrame())
    steps = (
        frame[f"{key}_step_minutes"].dropna().unique()
        if f"{key}_step_minutes" in frame
        else []
    )
    coverage.append(
        {
            "Series": label,
            "Actual slots": f"{count} / {len(frame)}",
            "Source interval": "Derived"
            if key == "residual_load" and count
            else ", ".join(f"{int(step)} min" for step in sorted(steps)) or "—",
            "Forecast": model_name(curve.model.iloc[0]) + " · " + curve.split.iloc[0]
            if not curve.empty
            else "Not available",
        }
    )
with st.expander(
    "Series availability & definitions",
    expanded=not any(not curve.empty for curve in curves.values()),
):
    st.dataframe(pd.DataFrame(coverage), hide_index=True, width="stretch")
    st.write(
        "Residual load = total load - solar - onshore wind - offshore wind, on matching intervals. Every component must be present; missing offshore data is not filled with zero. It is an observed series here. A custom residual-load forecast requires a DE-LU wind forecast."
    )
    st.caption(
        "Market curves use the latest cached ENTSO-E observations. Forecast detail uses each backtest's original targets; revisions can differ. No page load contacts an energy API."
    )

if all(key in frame for key in ["residual_load", "price", "solar"]):
    aligned = frame.dropna(subset=["residual_load", "price", "solar"])
    if not aligned.empty:
        st.subheader("Residual load & the price curve")
        st.plotly_chart(
            price_relationship(aligned), width="stretch", key="price_relationship"
        )
        st.write(
            "At unchanged supply and interconnector conditions, extra wind/solar reduces residual demand and can move clearing towards cheaper offers; higher load pushes the other way. The observed relationship also reflects fuel/carbon prices, outages, hydro, cross-border flows and market bids."
        )
        st.caption(
            "Each point is an observed interval on the selected day. This association is not a causal price-impact estimate or an input to the current price-only LEAR model."
        )
