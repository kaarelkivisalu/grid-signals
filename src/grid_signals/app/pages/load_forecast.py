"""DE-LU load forecasts complete another part of the fundamentals-to-price chain."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

from grid_signals.app.forecast_charts import fan_chart
from grid_signals.app.snapshot import MODEL_LABELS, SnapshotError, load_load_snapshot

st.caption("GRID SIGNALS / DE-LU LOAD")
st.title("Forecast the demand.")
st.write(
    "Tomorrow's total electricity load in Germany-Luxembourg, at 15-minute resolution."
)

try:
    snapshot = load_load_snapshot()
except SnapshotError:
    st.error("Load snapshot unavailable")
    st.stop()
if snapshot is None:
    st.info(
        "The first load benchmark is being prepared. Other forecast pages remain available."
    )
    st.stop()

st.caption("Target: total load including losses, excluding energy absorbed by storage.")
forecast = snapshot["forecast"]
if forecast:
    archived = (
        date.fromisoformat(forecast["delivery_date"])
        < datetime.now(ZoneInfo("Europe/Berlin")).date()
    )
    st.info(
        f"{'Archived research forecast' if archived else 'Research forecast'} · delivery {forecast['delivery_date']} · {forecast['publication_status'].replace('_', ' ')} publication"
    )
    st.caption(
        "Model selected on development CRPS: " + MODEL_LABELS[forecast["forecaster"]]
    )
    values = np.asarray(forecast["quantiles_mw"]["0.50"])
    first, second, third = st.columns(3)
    first.metric("Mean interval median", f"{values.mean():,.0f} MW")
    second.metric("Peak interval median", f"{values.max():,.0f} MW")
    third.metric("Market intervals", len(values))
    st.plotly_chart(
        fan_chart(forecast, "Europe/Berlin", kind="load"),
        width="stretch",
        key="load_forecast",
    )
    with st.expander("Publication record & download"):
        st.write(f"Information cutoff: {forecast['cutoff_at']}")
        st.write(
            f"Created: {forecast['created_at']} · published: {forecast['published_at']}"
        )
        st.code(forecast["forecast_id"], language=None)
        st.download_button(
            "Download load forecast",
            json.dumps({"unit": "MW", "zone": "DE_LU", **forecast}, indent=2),
            file_name="delu_load_forecast.json",
            mime="application/json",
        )


def comparison_table(rows: list[dict]) -> None:
    table = pd.DataFrame(rows)
    st.dataframe(
        pd.DataFrame(
            {
                "Method": table.name.map(MODEL_LABELS),
                "MAE (MW)": table.mae_mw.round(1),
                "CRPS (MW)": table.crps_mw.round(1),
                "80% coverage (%)": (table.coverage_80 * 100).round(1),
                "Relative MAE": table.relative_mae.round(3),
                "Days scored": table.days,
                "Days requested": table.requested_days,
            }
        ),
        hide_index=True,
        width="stretch",
    )


final = snapshot.get("final_evaluation")
if final:
    st.subheader("Final load holdout")
    st.write(
        f"{final['start']} to {final['end_exclusive']} exclusive. The selected model was fixed before opening this window."
    )
    comparison_table(final["metrics"])

evaluation = snapshot["evaluation"]
st.subheader("Development comparison")
st.write(
    f"{evaluation['start']} to {evaluation['end']} · monthly refits · seven-day embargo"
)
comparison_table(evaluation["metrics"])
st.caption(
    "Relative MAE below 1 improves on weekly persistence. Errors use MW, not renewable installed-capacity percentages."
)
st.warning(
    "Historical lagged load uses latest-revised observations with an assumed publication delay. Original historical revisions are not verified; live publication is evaluated separately."
)

st.subheader("Inspect a delivery day")
example_label = st.radio(
    "Load example", [row["label"] for row in evaluation["examples"]], horizontal=True
)
example = next(row for row in evaluation["examples"] if row["label"] == example_label)
comparison = st.selectbox(
    "Load comparison",
    list(example["comparisons_mw"]),
    format_func=lambda name: MODEL_LABELS[name],
)
st.caption(
    f"Delivery {example['delivery_date']} · median MAE {example['mae_mw']:,.0f} MW. Examples are selected by daily development-error rank."
)
st.plotly_chart(
    fan_chart(example, "Europe/Berlin", comparison=comparison, kind="load"),
    width="stretch",
    key="load_backtest",
)

card = snapshot.get("live_scorecard")
if card:
    st.subheader("Forward publication record")
    first, second, third = st.columns(3)
    first.metric("Load runs due", card["due_runs"])
    second.metric("On-time first issues", card["on_time_runs"])
    third.metric("Scored delivery days", card["scored_days"])

with st.expander("Data and model limits"):
    for limit in snapshot["limits"]:
        st.write(limit)
    st.write(
        "Temperature uses archived forecasts. Calendar includes known national holidays. Actual-load lags are at least 72 hours old relative to the target."
    )
    st.json(snapshot["protocol"]["policy"])

st.subheader("From load to residual load")
st.write(
    "A complete residual-load forecast also needs DE-LU onshore wind, offshore wind and solar under matching definitions. Custom German wind remains the missing component; residual load is not yet published."
)
