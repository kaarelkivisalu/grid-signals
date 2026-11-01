"""Shared portfolio navigation, availability choices and forecast presentation."""

from datetime import date
from html import escape

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
from grid_signals.app.model_catalogue import (
    FORECAST_GUIDES,
    REFERENCE_MODELS,
    model_name,
)
from grid_signals.app.snapshot import SnapshotError
from grid_signals.markets import (
    BY_CODE,
    MARKET_GROUPS,
    PORTFOLIO_MARKETS,
    SDAC_MARKETS,
    SELECTED_MODELS,
)

FAMILIES = {
    "wind_onshore": "Wind",
    "solar": "Solar",
    "price": "Prices",
    "load": "Demand",
}


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


def _choose_target(target: str) -> None:
    st.session_state.selected_target = target


def target_choices() -> str:
    if st.session_state.selected_target not in FAMILIES:
        st.session_state.selected_target = "wind_onshore"
    chosen = st.session_state.selected_target
    st.markdown(
        """<style>
        .st-key-target-selector button { border-radius: 0; min-height: 2rem; }
        </style>""",
        unsafe_allow_html=True,
    )
    with st.container(
        horizontal=True, width="content", gap=None, key="target-selector"
    ):
        for target, label in FAMILIES.items():
            st.button(
                label,
                key=f"target_{target}",
                type="primary" if target == chosen else "secondary",
                on_click=_choose_target,
                args=(target,),
            )
    return chosen


def process_diagram(steps: tuple[tuple[str, str, str], ...]) -> None:
    """A responsive, readable flow; the DOM order also conveys the sequence."""
    items = "".join(
        f"<li><span>{escape(label)}</span><strong>{escape(title)}</strong>"
        f"<p>{escape(detail)}</p>"
        + (
            '<svg class="process-arrow" viewBox="0 0 24 24" aria-hidden="true">'
            '<path d="M3 12h17m-6-6 6 6-6 6" fill="none" '
            'stroke="currentColor" stroke-width="1.5"/></svg>'
            if index < len(steps) - 1
            else ""
        )
        + "</li>"
        for index, (label, title, detail) in enumerate(steps)
    )
    st.markdown(
        """<style>
        [data-testid="stMarkdownContainer"] ol.process-flow {
            display: flex; list-style: none; padding: 0; margin: 1rem 0 1.5rem;
            gap: 1.5rem; width: 100%; max-width: none; }
        .process-flow li { position: relative; flex: 1; min-width: 0; border-top: 2px solid #147d77;
            padding-top: .75rem; }
        .process-arrow { position: absolute; width: 24px; height: 24px;
            right: -24px; top: 2.1rem; color: #147d77; }
        .process-flow span { display: block; color: #536963; margin-bottom: .35rem; }
        .process-flow strong { display: block; font-size: 1.15rem; color: #183c3b; }
        .process-flow p { margin: .5rem 0 0; line-height: 1.6; }
        @media(max-width: 700px) {
            .process-flow { flex-direction: column; gap: 1rem; }
            .process-arrow { display: none; }
        }
        </style>"""
        f'<ol class="process-flow">{items}</ol>',
        unsafe_allow_html=True,
    )


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
    models = sorted(forecasts.model.unique(), key=model_name)
    if st.session_state.get("selected_model") not in models:
        st.session_state.selected_model = (
            SELECTED_MODELS[target] if SELECTED_MODELS[target] in models else models[0]
        )
    with st.expander("Explore other forecast models"):
        st.write(
            "The default is the selected model for this product. Alternative models "
            "are saved research comparisons; their available dates may differ."
        )
        model = st.selectbox(
            "Forecast model", models, key="selected_model", format_func=model_name
        )
    pool = forecasts[forecasts.model == model]
    days = sorted(pool.delivery_date.unique())
    day = delivery_day(days, f"forecast_day_{zone}_{target}_{model}")
    if day not in days:
        st.info(
            "No saved forecast for this day. Use the arrows to find a saved result."
        )
        st.stop()
    rows = choose_curve(pool, target, day, model)
    scope = rows.split.iloc[0]
    if scope == "Final holdout":
        st.write(
            "Historical evaluation · Forecasts reconstructed for a held-out test period."
        )
    elif scope == "Development":
        st.write(
            "Development results · These dates were used to compare and select models."
        )
    if scope == "Published archive":
        issues = pool[
            (pool.delivery_date == day) & (pool.split == "Published archive")
        ].sort_values("published_at")
        ids = issues.forecast_id.unique().tolist()
        if len(ids) > 1:
            with st.expander("Earlier publications for this day"):
                st.write("The latest saved publication is shown by default.")
                chosen = st.selectbox(
                    "Publication time",
                    ids,
                    index=len(ids) - 1,
                    format_func=lambda value: pd.Timestamp(
                        issues.loc[issues.forecast_id == value, "published_at"].iloc[0]
                    ).strftime("%d %b %Y, %H:%M UTC"),
                    key=f"revision_{zone}_{target}_{model}_{day}",
                )
            rows = issues[issues.forecast_id == chosen].sort_values("valid_time")
        issue = rows.iloc[0]
        st.write(
            f"Published forecast · {issue.publication_status} · "
            f"published {issue.published_at} · input cutoff {issue.information_cutoff_at}"
        )
        if pd.notna(issue.get("training_max_day")):
            prepared_at = pd.Timestamp(issue.model_prepared_at).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            st.write(
                f"Training data ends **{issue.training_max_day}**. Saved model prepared **{prepared_at}**."
            )
        observed = read_market(manifest, zone, "observation")
        frame = market_day(observed, day, market.timezone)
        if target in frame:
            rows = rows.copy()
            rows["actual"] = (
                frame[target].reindex(pd.DatetimeIndex(rows.valid_time)).to_numpy()
            )
    reference_model = REFERENCE_MODELS[target]
    reference = choose_curve(
        forecasts[forecasts.split == scope], target, day, reference_model
    )
    if scope == "Published archive" and not rows.empty and "forecast_id" in forecasts:
        reference = forecasts[
            (forecasts.model == reference_model)
            & (forecasts.forecast_id == rows.forecast_id.iloc[0])
        ].sort_values("valid_time")
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
    st.subheader("About this forecast")
    st.write(
        f"**{model_name(model)}.** {FORECAST_GUIDES[target]['note']}"
        if model == SELECTED_MODELS[target]
        else f"**{model_name(model)}.** See the model guide for this comparison's inputs and limits."
    )
    if not reference.empty and model != reference_model:
        st.write(
            f"**{model_name(reference_model)}:** {FORECAST_GUIDES[target]['reference']}"
        )
    elif model != reference_model:
        st.write("A matching reference forecast is unavailable for this saved day.")
    st.write("The shaded 80% range runs from the 10th to the 90th percentile.")
    if rows.actual.notna().any():
        st.write("The lower panel shows forecast minus actual.")
    if st.button("Explore model inputs & methods", icon=":material/arrow_forward:"):
        st.session_state[f"method_model_{target}"] = model
        st.switch_page("pages/methods.py")
