"""Model recipes, actual inputs, evaluation boundaries and public competitors."""

import pandas as pd
import streamlit as st

from grid_signals.app.markets import BY_CODE, TARGETS
from grid_signals.app.model_catalogue import CATALOGUE, model_name
from grid_signals.app.snapshot import SnapshotError, load_price_snapshot, load_snapshot

manifest = st.session_state.explorer_manifest
zone = st.session_state.selected_zone
target = st.session_state.selected_target
info = manifest["zones"].get(zone, {})
models = info.get("targets", {}).get(target, {}).get("models", [])
st.title("What goes into the forecast")
st.write(
    f"**{BY_CODE[zone].name} · {TARGETS[target]}** · model recipes and information boundaries"
)
if not models:
    st.info(
        "There is no custom model for this market/target yet. The public data catalogue below describes comparison candidates, not completed benchmarks."
    )
for model in sorted(
    models, key=lambda key: (key != st.session_state.selected_model, model_name(key))
):
    recipe, features, uncertainty, resolution, limits = CATALOGUE[model]
    with st.expander(
        model_name(model), expanded=model == st.session_state.selected_model
    ):
        st.write(recipe)
        st.markdown("**Input features**")
        for feature in features:
            st.markdown(f"- {feature}")
        st.write(f"**Uncertainty:** {uncertainty}")
        st.write(f"**Time resolution:** {resolution}")
        st.write(f"**Limits:** {limits}")

st.subheader("From weather to clearing price")
st.markdown(
    "**Weather + fleet → wind / solar** · **temperature + calendar + load history → total load** · **load - wind - solar → residual load** · **fundamentals + market history → price**"
)
st.write(
    "SE3 onshore wind leads the Nordic/Baltic work; transfer to SE4 is the next research step. German solar, load and price models remain supporting case studies. The current price baseline uses price history only. Custom German wind and residual-load forecasts are deferred. Subtracting separate marginal quantiles does not produce residual-load quantiles: the components need matched scenarios or a dependence model."
)
st.subheader("Which information was available?")
st.write(
    "The declared cutoff is 09:00 UTC on the day before delivery. Weather endpoints and run age are checked against that boundary; lags must be observable by issue. Training uses rolling origins, with a seven-day embargo for renewables. Calibration uses training-side data. Completed final windows are reported separately from development model selection."
)
st.caption(
    "Historical forecasts are replays. Creation, cutoff and actual publication times are separate. The local daily trial records on-time, late, missing and failed issues; a late replay cannot demonstrate operational reliability. Historical actual revisions and annual installed-capacity publication vintages remain limitations."
)

st.subheader("Public forecasts & benchmark coverage")
st.write(
    "ENTSO-E day-ahead wind/solar curves use a documented 18:00 Brussels reference, later than this project's cutoff. A 'day-ahead' name alone does not establish comparability. Store issue/retrieval evidence, compare the same target and clock, and count producer mirrors once."
)
try:
    bundle = load_snapshot()
except SnapshotError:
    bundle = {}
sources = bundle.get("benchmark_sources", [])
if sources:
    table = pd.DataFrame(sources)
    st.dataframe(
        table[["label", "target", "coverage", "status", "eligible", "url"]],
        hide_index=True,
        width="stretch",
        column_config={"url": st.column_config.LinkColumn("Source")},
    )
st.caption(
    "These are inventory entries. None is shown as a scored competitor until eligible historical forecast vintages are available. Public auction prices are observations, not forecasts."
)
st.markdown(
    "[ENTSO-E definitions](https://eepublicdownloads.entsoe.eu/clean-documents/Transparency/MoP_Ref2_DDD_v3r4.pdf) · [Open-Meteo forecast archives](https://open-meteo.com/en/docs/previous-runs-api) · [Volue figure examples](https://docs.volue.com/data-and-forecasts/volue-insight-timeseries/guides/examples)"
)

try:
    price = load_price_snapshot()
except SnapshotError:
    price = None
if price and price.get("load_input_experiment"):
    with st.expander("Does custom load improve the price forecast?"):
        st.write(
            "The matched development ablation changed price MAE from €26.16 to €25.89/MWh with custom median load. Both median/quantile CRPS confidence intervals include zero. This does not establish added value on an independent test; the operational baseline remains price-only LEAR."
        )
        st.json(price["load_input_experiment"], expanded=False)
if price and price.get("decision_study"):
    with st.expander("DE-LU case study · flexible consumption"):
        st.write(
            "Offline development study: shift 1 MWh/day into eight quarter-hours at a maximum 0.5 MW, with interruptions allowed. Transaction fees, grid charges and taxes are excluded."
        )
        table = pd.DataFrame(price["decision_study"]["methods"])
        table["Method"] = table.Method.map(model_name)
        st.dataframe(table, hide_index=True, width="stretch")
        st.caption(
            "Simulation on development forecasts, not realised profit. Perfect information is an unattainable reference."
        )
with st.expander("Bundle provenance"):
    st.write(
        f"Exported {manifest['exported_at']}. Portable original predictions and observed series; no model training, database access or energy API calls occur when browsing."
    )
    st.caption(
        "SHA-256 hashes refer to local source artifacts at export. Observations are latest cached series, not proof of historical publication time."
    )
    st.dataframe(pd.DataFrame(manifest["sources"]), hide_index=True, width="stretch")
