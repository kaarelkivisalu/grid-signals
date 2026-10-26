"""Shared portfolio navigation, availability choices and forecast presentation."""

from datetime import date

import pandas as pd
import streamlit as st

from grid_signals.app.explorer_charts import (
    forecast_chart,
)
from grid_signals.app.explorer_data import (
    SCORED_SPLITS,
    choose_curve,
    market_day,
    read_market,
)
from grid_signals.app.markets import (
    BY_CODE,
    MARKET_GROUPS,
    PORTFOLIO_MARKETS,
    SDAC_MARKETS,
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


def market_choices(manifest: dict, target: str | None = None) -> str:
    """Group all areas; enable only those with data usable on this page."""
    available = (
        available_markets(manifest, target)
        if target
        else [
            code
            for code in SDAC_MARKETS
            if manifest["zones"].get(code, {}).get("observations")
            or manifest["zones"].get(code, {}).get("targets")
        ]
    )
    if not available:
        st.info("No saved data is available for this product yet.")
        st.stop()
    if st.session_state.selected_zone not in available and (
        target or st.session_state.selected_zone not in SDAC_MARKETS
    ):
        _choose_market(available[0])
    zone = st.session_state.selected_zone
    # The Map provides the full SDAC inventory; keep page controls compact.
    visible = (
        set(PORTFOLIO_MARKETS)
        | {zone}
        | {
            code
            for code in SDAC_MARKETS
            if manifest["zones"].get(code, {}).get("observations")
            or manifest["zones"].get(code, {}).get("targets")
        }
    )
    st.markdown(
        """<style>
        .st-key-area-selector [data-testid="stButton"] button {
            border-radius: 0; min-height: 2rem; padding: .2rem .6rem;
        }
        </style>""",
        unsafe_allow_html=True,
    )
    with st.container(horizontal=True, gap="small", key="area-selector"):
        for group, codes in MARKET_GROUPS.items():
            visible_codes = [code for code in codes if code in visible]
            if not visible_codes:
                continue
            with st.container(
                horizontal=True, width="content", gap=None, key=f"area-group-{group}"
            ):
                for code in visible_codes:
                    enabled = code in available
                    st.button(
                        code.replace("_", "-"),
                        key=f"market_{target or 'overview'}_{code}",
                        disabled=not enabled,
                        type="primary" if code == zone else "secondary",
                        help=f"{BY_CODE[code].name} · "
                        + ("saved data" if enabled else "not available yet"),
                        on_click=_choose_market,
                        args=(code,),
                    )
    return zone


def _set_delivery_day(key: str, value: date) -> None:
    st.session_state[key] = value
    st.session_state.delivery_date = value


def delivery_day(days: list[str], key: str) -> str:
    """A compact calendar with navigation between saved delivery days."""
    available = sorted(date.fromisoformat(day) for day in days)
    current = st.session_state.delivery_date
    selected = st.session_state.get(key) or current
    if not isinstance(selected, date):
        selected = available[-1]
    if not available[0] <= selected <= available[-1]:
        selected = available[-1]
    st.session_state[key] = selected
    before = [day for day in available if day < selected]
    after = [day for day in available if day > selected]
    st.markdown(
        """<style>
        .st-key-delivery-day-control {
            border: 1px solid #b8c4c4; border-radius: 3px;
        }
        .st-key-delivery-day-control:focus-within {
            outline: 2px solid #147d77; outline-offset: 2px;
        }
        .st-key-delivery-day-control [data-testid="stButton"] button {
            border: 0; border-radius: 0; min-height: 2.5rem; padding: 0;
        }
        .st-key-delivery-day-control [data-testid="stButton"] p {
            position: absolute; width: 1px; height: 1px; padding: 0;
            margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap;
        }
        .st-key-delivery-day-control [data-baseweb="input"] {
            border: 0; border-radius: 0;
        }
        </style>""",
        unsafe_allow_html=True,
    )
    with st.container(
        horizontal=True,
        width="content",
        vertical_alignment="center",
        gap=None,
        key="delivery-day-control",
    ):
        st.button(
            "Previous day",
            icon=":material/chevron_left:",
            width=36,
            key=f"previous_{key}",
            disabled=not before,
            help="Previous saved day",
            on_click=_set_delivery_day,
            args=(key, before[-1] if before else selected),
        )
        with st.container(width=160):
            selected = st.date_input(
                "Delivery date",
                min_value=available[0],
                max_value=available[-1],
                key=key,
                format="YYYY-MM-DD",
                label_visibility="collapsed",
            )
        st.button(
            "Next day",
            icon=":material/chevron_right:",
            width=36,
            key=f"next_{key}",
            disabled=not after,
            help="Next saved day",
            on_click=_set_delivery_day,
            args=(key, after[0] if after else selected),
        )
    if selected is None:
        st.info("Choose a delivery date.")
        st.stop()
    st.session_state.delivery_date = selected
    return selected.isoformat()


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
    kinds = [
        split
        for split in (*SCORED_SPLITS, "Published archive")
        if (forecasts.split == split).any()
    ]
    scope_key = f"chosen_archive_{target}"
    scope = st.session_state.get(scope_key, kinds[0])
    if scope not in kinds:
        scope = kinds[0]
    archive_column, model_column = st.columns(2)
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
    model = model_column.selectbox(
        "Model", models, key="selected_model", format_func=model_name
    )
    pool = pool[pool.model == model]
    days = sorted(pool.delivery_date.unique(), reverse=True)
    day = delivery_day(days, f"forecast_day_{zone}_{target}_{scope}_{model}")
    if day not in days:
        st.info(
            "No saved forecast for this day. Use the arrows to find a saved result."
        )
        st.stop()
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
        if len(ids) > 1:
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
            show_error=True,
        ),
        width="stretch",
        key="forecast_detail",
        config={"displayModeBar": False},
    )
    st.download_button(
        "Download forecast · CSV",
        rows.to_csv(index=False).encode(),
        file_name=f"{zone}-{target}-{day}.csv",
        mime="text/csv",
    )
    _recipe, _features, _uncertainty, resolution, limits = CATALOGUE[model]
    st.caption(f"{model_name(model)} · {resolution} {limits}")
    st.page_link("pages/methods.py", label="Model inputs & method")
