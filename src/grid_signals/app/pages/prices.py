"""DE-LU price forecasts and price-only benchmarks from portable artifacts."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

from grid_signals.app.forecast_charts import fan_chart
from grid_signals.app.snapshot import MODEL_LABELS, SnapshotError, load_price_snapshot

st.caption("GRID SIGNALS / DE-LU SPOT PRICES")
st.title("Forecast the auction.")
st.write("Day-ahead wholesale prices in Germany-Luxembourg, at 15-minute resolution.")

try:
    snapshot = load_price_snapshot()
except SnapshotError:
    st.error("Price snapshot unavailable")
    st.stop()
if snapshot is None:
    st.info(
        "The first DE-LU price benchmark is being prepared. Wind and solar research results are available on the other pages."
    )
    st.stop()

forecast = snapshot["forecast"]
if forecast:
    delivery = date.fromisoformat(forecast["delivery_date"])
    archived = delivery < datetime.now(ZoneInfo("Europe/Berlin")).date()
    label = "Archived research forecast" if archived else "Research forecast"
    st.info(
        f"{label} · delivery {forecast['delivery_date']} · {forecast['publication_status'].replace('_', ' ')} publication"
    )
    st.caption(
        "Forward baseline: "
        + MODEL_LABELS.get(
            forecast.get("forecaster"), "Experimental direct-quantile LightGBM"
        )
        + ". "
        + (
            "Hourly distributions repeated onto quarter-hours; uncertainty uses training-only residuals."
            if forecast.get("temporal_method") == "hourly_repeated"
            else "Native quarter-hour model; compare its interval coverage below."
        )
    )
    values = np.asarray(forecast["quantiles_eur_mwh"]["0.50"])
    first, second, third = st.columns(3)
    first.metric("Mean interval median", f"{values.mean():.2f} EUR/MWh")
    second.metric("Lowest interval median", f"{values.min():.2f} EUR/MWh")
    third.metric("Highest interval median", f"{values.max():.2f} EUR/MWh")
    st.plotly_chart(
        fan_chart(forecast, "Europe/Berlin", kind="price"),
        width="stretch",
        key="price_forecast",
    )
    with st.expander("Issue time, publication & download"):
        st.write(f"**Information cutoff:** {forecast['cutoff_at']}")
        st.write(f"**Created:** {forecast['created_at']}")
        st.write(f"**Published:** {forecast['published_at']}")
        st.code(forecast["forecast_id"], language=None)
        st.download_button(
            "Download price forecast",
            json.dumps({"zone": "DE_LU", "unit": "EUR/MWh", **forecast}, indent=2),
            file_name="delu_price_forecast.json",
            mime="application/json",
        )

st.subheader("Price-only benchmark")
evaluation = snapshot["evaluation"]
st.write(
    f"{evaluation['start']} to {evaluation['end']} · development evaluation · monthly refits and seven-day embargo"
)
st.caption(
    f"Final price holdout: {snapshot['holdout_status']}. Historical public fundamentals are excluded until their pre-cutoff vintages are verified."
)
table = pd.DataFrame(evaluation["metrics"])
display = pd.DataFrame(
    {
        "Method": table.name.map(MODEL_LABELS),
        "MAE (EUR/MWh)": table.mae,
        "CRPS (EUR/MWh)": table.crps,
        "80% coverage (%)": table.coverage_80 * 100,
        "Relative MAE": table.relative_mae,
        "Delivery days": table.days,
    }
)
st.dataframe(
    display,
    hide_index=True,
    width="stretch",
    column_config={
        column: st.column_config.NumberColumn(format="%.2f")
        for column in display
        if column not in {"Method", "Delivery days"}
    },
)
st.write(
    "Relative MAE is measured against the weekly naive forecast; below 1 means lower error. LEAR is an hourly price-only adaptation. Both GBM methods learn directly from genuine quarter-hour prices."
)
st.info(
    "LEAR leads this development comparison. The direct-quantile model's 80% interval covers only 62.5% of observations, so its uncertainty ranges need further validation."
)
st.caption(
    "Price errors are in EUR/MWh. They are not the capacity-normalised percentages used for wind and solar."
)

final = snapshot.get("final_evaluation")
if final:
    st.subheader("Final price holdout")
    st.write(
        f"{final['start']} to {final['end_exclusive']} exclusive · {final['requested_days']} requested days · fixed methods, no retuning."
    )
    final_table = pd.DataFrame(final["metrics"])
    st.dataframe(
        pd.DataFrame(
            {
                "Method": final_table.name.map(MODEL_LABELS),
                "MAE (EUR/MWh)": final_table.mae.round(2),
                "CRPS (EUR/MWh)": final_table.crps.round(2),
                "80% coverage (%)": (100 * final_table.coverage_80).round(1),
                "Days scored": final_table.days,
            }
        ),
        hide_index=True,
        width="stretch",
    )

card = snapshot.get("live_scorecard")
if card:
    st.subheader("Forward publication record")
    first, second, third = st.columns(3)
    first.metric("Price runs due", card["due_runs"])
    second.metric("On-time first issues", card["on_time_runs"])
    third.metric("Scored delivery days", card["scored_days"])
    st.caption(
        "Only original on-time issues are scored. Late forecasts and retries remain visible in the publication archive."
    )

inputs = snapshot.get("load_input_experiment")
if inputs:
    st.subheader("Do custom load forecasts help?")
    st.write(
        "Development experiment: the same price model with price-only inputs, added load medians, or added load quantiles. Upstream load fits and downstream price fits both precede their forecast dates."
    )
    input_table = pd.DataFrame(inputs["metrics"])
    labels = {
        "price_only": "Price history + calendar",
        "custom_load_point": "+ custom load median",
        "custom_load_quantiles": "+ custom load quantiles",
    }
    st.dataframe(
        pd.DataFrame(
            {
                "Inputs": input_table.name.map(labels),
                "MAE (EUR/MWh)": input_table.mae.round(2),
                "CRPS (EUR/MWh)": input_table.crps.round(2),
                "80% coverage (%)": (100 * input_table.coverage_80).round(1),
                "CRPS delta CI low": input_table.crps_delta_low.round(2),
                "CRPS delta CI high": input_table.crps_delta_high.round(2),
                "Days scored": input_table.days,
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "CRPS differences compare identical rows with the price-only arm; negative favours adding load. Day-block bootstrap 95% intervals. This is joint development evidence: model selection and historical actual-load revision assumptions require fresh forward confirmation."
    )

st.subheader("Inspect a delivery day")
label = st.radio(
    "Price example",
    [example["label"] for example in evaluation["examples"]],
    horizontal=True,
)
example = next(
    example for example in evaluation["examples"] if example["label"] == label
)
comparison = st.selectbox(
    "Price comparison",
    list(example["comparisons_eur_mwh"]),
    format_func=lambda name: MODEL_LABELS.get(name, name),
)
st.caption(
    f"Delivery {example['delivery_date']} · median MAE {example['mae']:.2f} EUR/MWh. Examples are selected by daily error rank."
)
st.plotly_chart(
    fan_chart(example, "Europe/Berlin", comparison=comparison, kind="price"),
    width="stretch",
    key="price_backtest",
)

decision = snapshot.get("decision_study")
if decision:
    st.subheader("What could a forecast change?")
    st.write(
        "Offline study: shift 1 MWh of flexible daily consumption into eight quarter-hours at a maximum 0.5 MW. Interruptions are allowed; no transaction fees, grid charges or taxes are modelled."
    )
    decision_table = pd.DataFrame(decision["methods"])
    decision_table["Method"] = decision_table.Method.map(
        lambda name: MODEL_LABELS.get(name, name)
    )
    st.dataframe(decision_table, hide_index=True, width="stretch")
    st.caption(
        "Simulation on development forecasts, not realised trading profit. Perfect information is an unattainable reference."
    )

st.subheader("Next: confirm useful inputs")
st.write(
    "LEAR is the forward price baseline. The first custom-load experiment shows a small, statistically unresolved gain for GBM; it does not establish that extra inputs earn their operating cost. Next, collect matched public and renewable forecasts and test on new forward dates."
)
