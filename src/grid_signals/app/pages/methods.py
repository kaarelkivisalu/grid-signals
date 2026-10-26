"""A compact source/feature table; exact recipes are available through Details."""

import pandas as pd
import streamlit as st

from grid_signals.app.markets import SELECTED_MODELS
from grid_signals.app.model_catalogue import (
    CATALOGUE,
    MODEL_DATA,
    input_rows,
    model_name,
)
from grid_signals.app.presentation import market_choices, page_heading, target_choices
from grid_signals.app.snapshot import SnapshotError, load_price_snapshot

manifest = st.session_state.explorer_manifest
detailed = page_heading("Models & data", "methods")
target = target_choices()
zone = market_choices(manifest, target, show_unavailable=detailed)
models = manifest["zones"][zone]["targets"][target]["models"]
model_key = f"chosen_method_{target}"
model = st.session_state.get(model_key, SELECTED_MODELS[target])
if model not in models:
    model = models[0]
if detailed:
    if st.session_state.get("method_model") not in models:
        st.session_state.method_model = model
    model = st.selectbox("Model", models, format_func=model_name, key="method_model")
st.session_state[model_key] = model
st.caption(f"{zone.replace('_', '-')} · {model_name(model)}")
st.table(
    pd.DataFrame(input_rows(model), columns=["Data source", "Used inputs"]).set_index(
        "Data source"
    ),
    border="horizontal",
)
if detailed:
    source, inputs, training = MODEL_DATA[model]
    recipe, features, uncertainty, resolution, limits = CATALOGUE[model]
    st.subheader("Recipe & training")
    st.write(recipe)
    st.write(f"**Sources:** {source}")
    st.write(f"**Forecast inputs:** {inputs}")
    st.write(f"**Fitting data:** {training}")
    for feature in features:
        st.markdown(f"- {feature}")
    st.write(f"**Uncertainty:** {uncertainty}")
    st.write(f"**Resolution:** {resolution}")
    st.write(f"**Limits:** {limits}")
    st.subheader("Other models")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Model": model_name(name),
                    "Sources": MODEL_DATA[name][0],
                    "Forecast inputs": MODEL_DATA[name][1],
                    "Fitting data": MODEL_DATA[name][2],
                }
                for name in models
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.subheader("Timing & provenance")
    st.write(
        "Inputs must be available by 09:00 UTC on the day before delivery. Renewable training uses a seven-day embargo; calibration uses training-side data. Final evaluation is kept separate from development model selection."
    )
    st.write(
        "Historical actual revisions and capacity vintages remain limitations. Replays do not prove on-time publication. Public forecasts with later cutoffs are excluded as scored competitors without eligible issue-time evidence."
    )
    st.markdown(
        "[ENTSO-E definitions](https://eepublicdownloads.entsoe.eu/clean-documents/Transparency/MoP_Ref2_DDD_v3r4.pdf) · [Open-Meteo forecast archives](https://open-meteo.com/en/docs/previous-runs-api)"
    )
    st.caption(f"Result export: {manifest['exported_at']}")
    st.dataframe(pd.DataFrame(manifest["sources"]), hide_index=True, width="stretch")
    if target in {"price", "load"}:
        try:
            price = load_price_snapshot()
        except SnapshotError:
            price = None
        if price:
            st.subheader("German case studies")
            if price.get("load_input_experiment"):
                st.write(
                    "Adding custom demand forecasts changed development price MAE from €26.16 to €25.89/MWh. Both distribution-error confidence intervals include zero; an independent improvement is unresolved. LEAR remains the baseline."
                )
            if price.get("decision_study"):
                st.write(
                    "Flexible consumption: move 1 MWh into eight quarter-hours per day, at up to 0.5 MW. Fees, grid charges and taxes are excluded. Development simulation, not realised profit."
                )
                table = pd.DataFrame(price["decision_study"]["methods"])
                table["Method"] = table.Method.map(model_name)
                st.dataframe(table, hide_index=True, width="stretch")
