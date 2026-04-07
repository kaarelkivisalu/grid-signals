"""Briefing viewer page."""

import streamlit as st

from grid_signals.app.main import get_db
from grid_signals.db.queries import get_briefing, list_briefing_dates

st.set_page_config(page_title="Briefings — Grid Signals", page_icon="⚡", layout="wide")
st.title("Daily Briefings")

con = get_db()
dates = list_briefing_dates(con)

if not dates:
    st.info("No briefings found. Generate one with `uv run grid-signals briefing`.")
else:
    labels = [d.isoformat() for d in dates]
    selected = st.selectbox("Select date", labels, index=0)
    if selected:
        from datetime import date

        briefing_date = date.fromisoformat(selected)
        result = get_briefing(con, briefing_date)
        if result:
            content, created_at = result
            st.caption(f"Generated at {created_at:%Y-%m-%d %H:%M} UTC")
            st.markdown(content)
