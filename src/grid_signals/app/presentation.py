"""Shared portfolio navigation, availability choices and forecast presentation."""

from datetime import date

import pandas as pd
import streamlit as st

from grid_signals.app.explorer_charts import (
    error_chart,
    forecast_chart,
    fundamentals_chart,
)
from grid_signals.app.explorer_data import (
    SCORED_SPLITS,
    choose_curve,
    grouped_scores,
    market_day,
    matched_rows,
    read_market,
)
from grid_signals.app.markets import (
    BY_CODE,
    PORTFOLIO_MARKETS,
    SELECTED_MODELS,
)
from grid_signals.app.model_catalogue import CATALOGUE, model_name
from grid_signals.app.snapshot import SnapshotError

FAMILIES = {"wind_onshore": "Wind", "solar": "Solar", "price": "Prices", "load": "Load"}


def available_markets(manifest: dict, target: str) -> list[str]:
    return [
        zone
        for zone in PORTFOLIO_MARKETS
        if any(
            manifest["zones"]
            .get(zone, {})
            .get("targets", {})
            .get(target, {})
            .get("dates_by_split", {})
            .get(split)
            for split in SCORED_SPLITS
        )
    ]


def _choose_market(zone: str) -> None:
    st.session_state.selected_zone = zone
    st.session_state.selected_model = None


def market_choices(manifest: dict, target: str) -> str:
    """Only enable markets with evaluated forecasts for the chosen target."""
    available = available_markets(manifest, target)
    if not available:
        st.info("No evaluated forecasts are available for this target yet.")
        st.stop()
    if st.session_state.selected_zone not in available:
        _choose_market(available[0])
    zone = st.session_state.selected_zone
    with st.container(horizontal=True, gap="small"):
        for code in PORTFOLIO_MARKETS:
            enabled = code in available
            st.button(
                code.replace("_", "-"),
                key=f"market_{target}_{code}",
                disabled=not enabled,
                type="primary" if code == zone else "secondary",
                help=f"{BY_CODE[code].name} · "
                + ("evaluated forecasts" if enabled else "no evaluated forecast yet"),
                on_click=_choose_market,
                args=(code,),
            )
    st.caption(
        "Choose a market. Grey markets do not yet have evaluated forecasts for this target."
    )
    return zone


def target_choices() -> str:
    if st.session_state.selected_target not in FAMILIES:
        st.session_state.selected_target = "wind_onshore"
    chosen = st.segmented_control(
        "Forecast target",
        list(FAMILIES),
        format_func=FAMILIES.get,
        key="selected_target",
    )
    return chosen or "wind_onshore"


def evaluated_forecasts(manifest: dict, zone: str) -> pd.DataFrame:
    try:
        return read_market(manifest, zone, "forecast")
    except SnapshotError as exc:
        st.error(str(exc))
        st.stop()


def final_scores(manifest: dict, zone: str, target: str) -> pd.DataFrame:
    frame = evaluated_forecasts(manifest, zone)
    frame = frame[(frame.target == target) & (frame.split == "Final holdout")]
    models = sorted(frame.model.unique())
    return grouped_scores(
        matched_rows(frame, models),
        "Overall",
        BY_CODE[zone].timezone,
        capacity=target in {"wind_onshore", "solar"},
    )


def render_forecast(target: str) -> None:
    st.session_state.selected_target = target
    manifest = st.session_state.explorer_manifest
    st.title(
        {
            "wind_onshore": "Wind generation",
            "solar": "Solar generation",
            "price": "Electricity prices",
            "load": "Electricity demand",
        }[target]
    )
    zone = market_choices(manifest, target)
    market = BY_CODE[zone]
    forecasts = evaluated_forecasts(manifest, zone)
    forecasts = forecasts[forecasts.target == target]
    date_column, note_column = st.columns([1, 2])
    with st.expander("Model & archive options"):
        kinds = [
            split
            for split in (*SCORED_SPLITS, "Published archive")
            if (forecasts.split == split).any()
        ]
        scope = st.radio(
            "Result archive",
            kinds,
            horizontal=True,
            key=f"archive_{target}",
            format_func=lambda value: {
                "Final holdout": "Final evaluation",
                "Development": "Development",
                "Published archive": "Saved published issues",
            }[value],
        )
        pool = forecasts[forecasts.split == scope]
        models = sorted(pool.model.unique())
        if st.session_state.get("selected_model") not in models:
            st.session_state.selected_model = (
                SELECTED_MODELS[target]
                if SELECTED_MODELS[target] in models
                else models[0]
            )
        model = st.selectbox(
            "Model", models, key="selected_model", format_func=model_name
        )
        full_intervals = st.toggle("Show all uncertainty bands", value=False)
    pool = pool[pool.model == model]
    days = sorted(pool.delivery_date.unique(), reverse=True)
    current = st.session_state.delivery_date
    current = current.isoformat() if isinstance(current, date) else current
    day = date_column.selectbox(
        "Delivery date",
        days,
        index=days.index(current) if current in days else 0,
        key=f"forecast_day_{zone}_{target}_{scope}_{model}",
    )
    st.session_state.delivery_date = date.fromisoformat(day)
    note_column.caption(f"{zone.replace('_', '-')} · {market.name} · {market.timezone}")
    rows = choose_curve(pool, target, day, model)
    if scope == "Published archive":
        issues = pool[pool.delivery_date == day].sort_values("published_at")
        ids = issues.forecast_id.unique().tolist()
        if len(ids) > 1:
            chosen = st.selectbox(
                "Issue / revision",
                ids,
                index=len(ids) - 1,
                format_func=lambda value: str(value)[:8],
            )
            rows = issues[issues.forecast_id == chosen].sort_values("valid_time")
        issue = rows.iloc[0]
        st.info(
            f"{issue.publication_status} · published {issue.published_at} · cutoff {issue.information_cutoff_at}"
        )
        observed = read_market(manifest, zone, "observation")
        frame = market_day(observed, day, market.timezone)
        if target in frame:
            rows = rows.copy()
            rows["actual"] = (
                frame[target].reindex(pd.DatetimeIndex(rows.valid_time)).to_numpy()
            )
    else:
        st.caption(
            f"{'Final evaluation' if scope == 'Final holdout' else 'Development comparison'} · {model_name(model)} · historical forecast"
        )
    reference_model = {
        "wind_onshore": "physical_power_curve",
        "solar": "smart_persistence",
        "price": "seasonal_naive",
        "load": "load_weekly",
    }[target]
    reference = choose_curve(
        forecasts[forecasts.split == scope], target, day, reference_model
    )
    st.plotly_chart(
        forecast_chart(
            rows,
            market.timezone,
            target,
            reference if model != reference_model else None,
            full_intervals=full_intervals,
        ),
        width="stretch",
        key="forecast_detail",
    )
    st.caption(
        (
            "Shaded areas show the 50%, 80% and 90% prediction ranges. "
            if full_intervals
            else "The shaded area shows the 80% prediction range. "
        )
        + "Actuals, when available, show what happened."
        + (
            " The reference is a simpler forecasting method."
            if not reference.empty and model != reference_model
            else ""
        )
    )
    with st.container(horizontal=True):
        st.page_link("pages/performance.py", label="Compare model performance")
        st.page_link("pages/methods.py", label="See data & model inputs")
    with st.expander("Errors, assumptions & downloads"):
        if rows.actual.notna().any():
            st.plotly_chart(error_chart(rows, market.timezone, target), width="stretch")
            st.caption(
                "Positive error means overprediction. Published issues use the latest cached actuals here; evaluation scores use their original targets."
            )
        recipe, _features, uncertainty, resolution, limits = CATALOGUE[model]
        st.write(recipe)
        st.write(f"**Uncertainty:** {uncertainty}")
        st.write(f"**Resolution:** {resolution}")
        st.write(f"**Limits:** {limits}")
        st.caption(
            "Information cutoff: 09:00 UTC on the preceding day. Historical replays do not prove on-time publication."
        )
        st.download_button(
            "Download this forecast · CSV",
            rows.to_csv(index=False).encode(),
            file_name=f"{zone}-{target}-{day}.csv",
            mime="text/csv",
        )
    with st.expander("Market observations & electricity prices"):
        observed = read_market(manifest, zone, "observation")
        frame = market_day(observed, day, market.timezone)
        series = [
            key
            for key in (
                "load",
                "solar",
                "wind_onshore",
                "wind_offshore",
                "residual_load",
            )
            if key in frame and frame[key].notna().any()
        ]
        st.plotly_chart(
            fundamentals_chart(frame, {target: rows}, market.timezone, series),
            width="stretch",
        )
        st.caption(
            "Generation and demand are in GW; prices are EUR/MWh. Missing observations stay missing. Residual demand needs all generation components; marginal prediction ranges cannot be subtracted to create its uncertainty."
        )
        steps = {
            key: sorted(frame[f"{key}_step_minutes"].dropna().unique().tolist())
            for key in [*series, "price"]
            if f"{key}_step_minutes" in frame
        }
        st.write("Original measurement intervals (minutes)")
        st.json(steps, expanded=False)
