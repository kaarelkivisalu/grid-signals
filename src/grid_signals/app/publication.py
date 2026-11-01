"""Public publication history and matched forward evidence, separate from research."""

from datetime import UTC, date, datetime
from operator import itemgetter

import pandas as pd
import streamlit as st


def render(manifest: dict, *, details: bool = False) -> None:
    record = manifest.get("_publication", {"status": "not_started", "issues": []})
    st.subheader("Daily SE3 wind")
    if record["status"] == "not_started":
        st.write(
            "Daily publication has not started for the saved-model producer. The charts below show historical results."
        )
        return
    rows = record["issues"]
    published = [row for row in rows if row.get("published_at")]
    latest = max(published, key=itemgetter("published_at")) if published else None
    due = [
        row
        for row in rows
        if datetime.fromisoformat(row["deadline_at"]) < datetime.now(UTC)
    ]
    if record.get("snapshot_stale"):
        st.warning(
            "The publication record has not updated for over 45 minutes. The producer may be unavailable."
        )
    if due and due[-1]["status"] != "on_time":
        st.warning(
            f"The latest due issue ({due[-1]['issue_day']}) is {due[-1]['status'].replace('_', ' ')}. Earlier results remain available."
        )
    if latest:
        published_at = datetime.fromisoformat(latest["published_at"]).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        st.write(
            f"Latest delivery day: **{latest['delivery_day']}**. Published **{published_at}** · {latest['status'].replace('_', ' ')}."
        )
        if st.button(
            "Open latest SE3 wind forecast",
            key=f"latest_se3_{'detail' if details else 'summary'}",
        ):
            st.session_state.selected_zone = "SE3"
            st.session_state.selected_target = "wind_onshore"
            st.session_state.selected_model = "hourly_repeated"
            st.session_state.delivery_date = date.fromisoformat(latest["delivery_day"])
            st.switch_page("pages/wind.py")
    else:
        st.write("No verified SE3 publication is recorded yet.")
    if not details:
        return
    gate = record.get("reliability_gate", {})
    st.write(
        f"Reliability check: {gate.get('consecutive_on_time', 0)} consecutive on-time issues; 30 are required. Historical replay does not count."
    )
    table = []
    for row in reversed(rows):
        scores = row.get("score") or {}
        model = scores.get("model", {})
        reference = scores.get("physical_reference", {})
        table.append(
            {
                "Issue day": row["issue_day"],
                "Delivery day": row["delivery_day"],
                "Publication": row["status"].replace("_", " "),
                "Published (UTC)": row.get("published_at"),
                "Model error (% capacity)": 100 * model["nmae"] if model else None,
                "Public forecast error (% capacity)": 100
                * scores["public_reference"]["nmae"]
                if scores.get("public_reference")
                else None,
                "Physical error (% capacity)": 100 * reference["nmae"]
                if reference
                else None,
                "Bias · actual - forecast (% capacity)": 100 * model["nbias"]
                if model
                else None,
                "80% range coverage (%)": 100 * model["coverage_80"] if model else None,
            }
        )
    st.write(
        f"{sum(row.get('score') is not None for row in due)} of {len(due)} due issues have complete actuals and scores."
    )
    frame = pd.DataFrame(table)
    if not frame.empty:
        display = frame.copy()
        for column in display.columns[4:]:
            display[column] = display[column].map(
                lambda value: f"{value:.2f}" if pd.notna(value) else "Unavailable"
            )
        st.dataframe(display, hide_index=True, width="stretch")
        st.download_button(
            "Download publication record · CSV",
            frame.to_csv(index=False).encode(),
            file_name="SE3-wind-publication.csv",
            mime="text/csv",
        )
    st.write(
        "Forward scores use the first forecast delivered before 09:30 UTC, on complete actual delivery days. Actuals and scores can be revised. Physical-reference comparisons use identical intervals; historical evaluation is separate."
    )
    with st.expander("Job status, models and collection evidence"):
        st.json(record)
