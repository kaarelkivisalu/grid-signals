"""Explicit data sources, forecast-time inputs and fitting data for every model."""

import pandas as pd
import streamlit as st

from grid_signals.app.markets import TARGETS
from grid_signals.app.model_catalogue import CATALOGUE, MODEL_DATA, model_name
from grid_signals.app.presentation import market_choices, target_choices
from grid_signals.app.snapshot import SnapshotError, load_price_snapshot

manifest = st.session_state.explorer_manifest
st.title("What each model uses")
st.write(
    "Data sources, inputs known before delivery, and the historical data used to fit each model."
)
target = target_choices()
zone = market_choices(manifest, target)
models = manifest["zones"][zone]["targets"][target]["models"]
model = st.radio(
    "Model", models, format_func=model_name, horizontal=True, key="method_model"
)
st.subheader(model_name(model))
source, inputs, training = MODEL_DATA[model]
st.markdown("**Data sources**")
st.write(source)
st.markdown("**Inputs when making a forecast**")
st.write(inputs)
st.markdown("**Historical data used to fit the model**")
st.write(training)
recipe, features, uncertainty, resolution, limits = CATALOGUE[model]
with st.expander("Exact feature families, algorithm & uncertainty"):
    st.write(recipe)
    for feature in features:
        st.markdown(f"- {feature}")
    st.write(f"**Uncertainty:** {uncertainty}")
    st.write(f"**Resolution:** {resolution}")
    st.write(f"**Limits:** {limits}")
with st.expander(f"Compare all {TARGETS[target].lower()} model inputs"):
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Model": model_name(name),
                    "Data sources": MODEL_DATA[name][0],
                    "Forecast-time inputs": MODEL_DATA[name][1],
                    "Fitting data": MODEL_DATA[name][2],
                }
                for name in models
            ]
        ),
        hide_index=True,
        width="stretch",
    )
with st.expander("Information timing & evaluation rules"):
    st.write(
        "The information cutoff is 09:00 UTC on the day before delivery. Weather runs and lags must be available by that boundary. Renewable training uses a seven-day embargo; calibration uses training-side data."
    )
    st.write(
        "Development selects models. Completed final evaluation is reported separately. Replays do not establish on-time publication; saved issues retain their creation, cutoff and publication times."
    )
    st.write(
        "Historical actual revisions and installed-capacity publication vintages remain limitations. Subtracting separate renewable quantiles does not produce a valid residual-demand distribution."
    )
with st.expander("Sources & result provenance"):
    st.markdown(
        "[ENTSO-E data definitions](https://eepublicdownloads.entsoe.eu/clean-documents/Transparency/MoP_Ref2_DDD_v3r4.pdf) · [Open-Meteo forecast archives](https://open-meteo.com/en/docs/previous-runs-api)"
    )
    st.write(
        "ENTSO-E public wind/solar forecasts use a later reference time than this project's cutoff. They are not scored competitors without eligible historical issue-time evidence."
    )
    st.caption(
        f"Results exported {manifest['exported_at']}. Page requests read saved files; they do not train a model or contact an electricity/weather API."
    )
    st.dataframe(pd.DataFrame(manifest["sources"]), hide_index=True, width="stretch")

if target in {"price", "load"}:
    try:
        price = load_price_snapshot()
    except SnapshotError:
        price = None
    if price:
        with st.expander("German case studies: demand inputs & flexible consumption"):
            if price.get("load_input_experiment"):
                st.write(
                    "Adding custom demand forecasts changed development price MAE from €26.16 to €25.89/MWh. Both distribution-error confidence intervals include zero, so this does not establish an independent improvement. LEAR remains the price baseline."
                )
                st.json(price["load_input_experiment"], expanded=False)
            if price.get("decision_study"):
                st.write(
                    "Offline development study: move 1 MWh of consumption into eight quarter-hours per day at a maximum 0.5 MW. Fees, grid charges and taxes are excluded. This is a simulation, not realised profit."
                )
                table = pd.DataFrame(price["decision_study"]["methods"])
                table["Method"] = table.Method.map(model_name)
                st.dataframe(table, hide_index=True, width="stretch")
