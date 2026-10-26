"""Shared portfolio navigation, availability choices and forecast presentation."""

from datetime import date

import pandas as pd
import streamlit as st

from grid_signals.app.explorer_charts import (
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


def market_choices(
    manifest: dict, target: str, *, show_unavailable: bool = False
) -> str:
    """Only enable markets with evaluated forecasts for the chosen target."""
    available = available_markets(manifest, target)
    if not available:
        st.info("No evaluated forecasts are available for this target yet.")
        st.stop()
    if st.session_state.selected_zone not in available:
        _choose_market(available[0])
    zone = st.session_state.selected_zone
    if not show_unavailable and len(available) == 1:
        return zone
    with st.container(horizontal=True, gap="small"):
        for code in PORTFOLIO_MARKETS if show_unavailable else available:
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
    return zone


def target_choices() -> str:
    if st.session_state.selected_target not in FAMILIES:
        st.session_state.selected_target = "wind_onshore"
    chosen = st.segmented_control(
        "Forecast target",
        list(FAMILIES),
        format_func=FAMILIES.get,
        key="selected_target",
        label_visibility="collapsed",
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


def page_heading(title: str, key: str) -> bool:
    heading, switch = st.columns([4, 1], vertical_alignment="center")
    heading.title(title)
    return switch.toggle("Details", key=f"details_{key}")


def render_forecast(target: str) -> None:
    st.session_state.selected_target = target
    manifest = st.session_state.explorer_manifest
    detailed = page_heading(
        {
            "wind_onshore": "Wind generation",
            "solar": "Solar generation",
            "price": "Electricity prices",
            "load": "Electricity demand",
        }[target],
        target,
    )
    zone = market_choices(manifest, target, show_unavailable=detailed)
    market = BY_CODE[zone]
    forecasts = evaluated_forecasts(manifest, zone)
    forecasts = forecasts[forecasts.target == target]
    kinds = [
        split
        for split in (*SCORED_SPLITS, "Published archive")
        if (forecasts.split == split).any()
    ]
    scope_key = f"chosen_archive_{target}"
    scope = st.session_state.get(scope_key, kinds[0])
    if scope not in kinds:
        scope = kinds[0]
    if detailed:
        archive_column, model_column, date_column = st.columns(3)
        scope = archive_column.selectbox(
            "Archive",
            kinds,
            index=kinds.index(scope),
            key=f"archive_{target}",
            format_func=lambda value: {
                "Final holdout": "Final evaluation",
                "Development": "Development",
                "Published archive": "Published issues",
            }[value],
        )
    st.session_state[scope_key] = scope
    pool = forecasts[forecasts.split == scope]
    models = sorted(pool.model.unique())
    if st.session_state.get("selected_model") not in models:
        st.session_state.selected_model = (
            SELECTED_MODELS[target] if SELECTED_MODELS[target] in models else models[0]
        )
    model = st.session_state.selected_model
    if detailed:
        model = model_column.selectbox(
            "Model", models, key="selected_model", format_func=model_name
        )
    pool = pool[pool.model == model]
    days = sorted(pool.delivery_date.unique(), reverse=True)
    current = st.session_state.delivery_date
    current = current.isoformat() if isinstance(current, date) else current
    day = current if current in days else days[0]
    full_intervals = False
    if detailed:
        day = date_column.selectbox(
            "Delivery date",
            days,
            index=days.index(day),
            key=f"forecast_day_{zone}_{target}_{scope}_{model}",
        )
        full_intervals = st.checkbox("Show 50% and 90% ranges", value=False)
    st.session_state.delivery_date = date.fromisoformat(day)
    scope_label = {
        "Final holdout": "Final evaluation",
        "Development": "Development",
        "Published archive": "Published issue",
    }[scope]
    st.caption(
        f"{zone.replace('_', '-')} · {market.name} · {date.fromisoformat(day):%d %b %Y} · {scope_label}"
    )
    rows = choose_curve(pool, target, day, model)
    if scope == "Published archive":
        issues = pool[pool.delivery_date == day].sort_values("published_at")
        ids = issues.forecast_id.unique().tolist()
        if detailed and len(ids) > 1:
            chosen = st.selectbox(
                "Issue / revision",
                ids,
                index=len(ids) - 1,
                format_func=lambda value: str(value)[:8],
            )
            rows = issues[issues.forecast_id == chosen].sort_values("valid_time")
        issue = rows.iloc[0]
        st.caption(
            f"{issue.publication_status} · published {issue.published_at} · cutoff {issue.information_cutoff_at}"
        )
        observed = read_market(manifest, zone, "observation")
        frame = market_day(observed, day, market.timezone)
        if target in frame:
            rows = rows.copy()
            rows["actual"] = (
                frame[target].reindex(pd.DatetimeIndex(rows.valid_time)).to_numpy()
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
            show_error=detailed,
        ),
        width="stretch",
        key="forecast_detail",
        config={"displayModeBar": detailed},
    )
    if not detailed:
        return
    st.download_button(
        "Download forecast · CSV",
        rows.to_csv(index=False).encode(),
        file_name=f"{zone}-{target}-{day}.csv",
        mime="text/csv",
    )
    st.subheader("Method")
    recipe, _features, uncertainty, resolution, limits = CATALOGUE[model]
    st.write(f"**{model_name(model)}.** {recipe}")
    st.write(f"**Range:** {uncertainty}")
    st.write(f"**Resolution:** {resolution}")
    st.write(f"**Limits:** {limits}")
    st.caption(
        "Information cutoff: 09:00 UTC on the preceding day. Historical replays do not prove on-time publication."
    )
    st.subheader("Market observations")
    observed = read_market(manifest, zone, "observation")
    frame = market_day(observed, day, market.timezone)
    series = [
        key
        for key in ("load", "solar", "wind_onshore", "wind_offshore", "residual_load")
        if key in frame and frame[key].notna().any()
    ]
    st.plotly_chart(
        fundamentals_chart(frame, {target: rows}, market.timezone, series),
        width="stretch",
    )
    st.caption(
        "Generation and demand: GW. Prices: EUR/MWh. Missing components stay missing; separate prediction ranges cannot be subtracted to give residual-demand uncertainty."
    )
    steps = {
        key: sorted(frame[f"{key}_step_minutes"].dropna().unique().tolist())
        for key in [*series, "price"]
        if f"{key}_step_minutes" in frame
    }
    st.write("Source intervals (minutes)")
    st.json(steps, expanded=False)
