"""Explain each forecast approach before its regional applications."""

import pandas as pd
import streamlit as st

from grid_signals.app.model_catalogue import (
    CATALOGUE,
    FORECAST_GUIDES,
    MODEL_DATA,
    REFERENCE_MODELS,
    input_rows,
    model_name,
)
from grid_signals.app.presentation import process_diagram, target_choices
from grid_signals.app.snapshot import SnapshotError, load_price_snapshot
from grid_signals.markets import BY_CODE, SELECTED_MODELS

manifest = st.session_state.explorer_manifest
st.title("Models & data")
st.write(
    "Each approach turns information available before delivery into a forecast and "
    "a prediction range. Simple references test whether the extra modelling helps."
)
target = target_choices()
guide = FORECAST_GUIDES[target]
selected_model = SELECTED_MODELS[target]
reference = REFERENCE_MODELS[target]
st.subheader(guide["question"])
process_diagram(guide["steps"])
st.write(f"**Comparison: {model_name(reference)}.** {guide['reference']}")
st.write(guide["note"])

st.subheader("Where it is tested")
applications = []
for zone, info in manifest["zones"].items():
    saved = info.get("targets", {}).get(target)
    if not saved:
        continue
    dates = saved["dates_by_split"].get("Final holdout", [])
    applications.append(
        {
            "Area": f"{zone.replace('_', '-')} · {BY_CODE[zone].name}",
            "Selected model": model_name(selected_model),
            "Final evaluation": f"{min(dates)} to {max(dates)}"
            if dates
            else "Not available",
        }
    )
st.table(pd.DataFrame(applications).set_index("Area"), border="horizontal")
if st.button("Explore these forecasts", icon=":material/arrow_forward:"):
    st.switch_page(
        f"pages/{ {'wind_onshore': 'wind', 'solar': 'solar', 'price': 'price', 'load': 'load'}[target] }.py"
    )

with st.expander("Sources, fitting data & detailed recipes"):
    models = sorted(
        {
            model
            for info in manifest["zones"].values()
            for model in info.get("targets", {}).get(target, {}).get("models", [])
        },
        key=model_name,
    )
    model_key = f"method_model_{target}"
    if st.session_state.get(model_key) not in models:
        st.session_state[model_key] = selected_model
    model = st.selectbox("Model recipe", models, format_func=model_name, key=model_key)
    st.table(
        pd.DataFrame(
            input_rows(model), columns=["Data source", "Used inputs"]
        ).set_index("Data source"),
        border="horizontal",
    )
    source, inputs, training = MODEL_DATA[model]
    recipe, features, uncertainty, resolution, limits = CATALOGUE[model]
    st.write(f"**Recipe:** {recipe}")
    st.write(f"**Forecast inputs:** {inputs}")
    st.write(f"**Fitting data:** {training}")
    st.write(f"**Uncertainty:** {uncertainty}")
    st.write(f"**Resolution:** {resolution}")
    st.write(f"**Limits:** {limits}")
    st.markdown("**Exact feature families**")
    for feature in features:
        st.write(f"- {feature}")

st.subheader("How the comparison stays fair")
process_diagram(
    (
        (
            "Before delivery",
            "09:00 UTC input cutoff",
            "Use only inputs available by the day-before cutoff. Historical weather publication age is approximated conservatively.",
        ),
        (
            "Before scoring",
            "Keep test dates separate",
            "Fit and calibrate on training data. Renewable training leaves a seven-day gap before scored dates.",
        ),
        (
            "After delivery",
            "Compare with actuals",
            "Score models on matching eligible intervals. Reconstructed forecasts do not establish on-time publication.",
        ),
    )
)
with st.expander("Timing assumptions & source definitions"):
    st.write(
        "Historical actual revisions and capacity vintages remain limitations. "
        "Public forecasts with later cutoffs are excluded as scored competitors "
        "without eligible issue-time evidence."
    )
    st.markdown(
        "[ENTSO-E definitions](https://eepublicdownloads.entsoe.eu/clean-documents/Transparency/MoP_Ref2_DDD_v3r4.pdf) · "
        "[Open-Meteo forecast archives](https://open-meteo.com/en/docs/previous-runs-api)"
    )

if target in {"price", "load"}:
    try:
        price = load_price_snapshot()
    except SnapshotError:
        price = None
    if price:
        with st.expander("Related German experiments"):
            if price.get("load_input_experiment"):
                st.write(
                    "Adding custom demand forecasts changed development price MAE from "
                    "€26.16 to €25.89/MWh. Both distribution-error confidence intervals "
                    "include zero; an independent improvement is unresolved. LEAR remains the baseline."
                )
            if price.get("decision_study"):
                st.write(
                    "Flexible consumption: move 1 MWh into eight quarter-hours per day, "
                    "at up to 0.5 MW. Fees, grid charges and taxes are excluded. "
                    "Development simulation, not realised profit."
                )
                table = pd.DataFrame(price["decision_study"]["methods"])
                table["Method"] = table.Method.map(model_name)
                st.dataframe(table, hide_index=True, width="stretch")
