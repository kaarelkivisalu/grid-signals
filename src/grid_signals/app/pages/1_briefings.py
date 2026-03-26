"""Briefing viewer page."""

from pathlib import Path

import streamlit as st

from grid_signals.briefing import DEFAULT_OUTPUT_DIR

st.set_page_config(page_title="Briefings — Grid Signals", page_icon="⚡", layout="wide")
st.title("Daily Briefings")


def _list_briefings(directory: Path) -> list[Path]:
    """List briefing markdown files sorted by date descending."""
    if not directory.exists():
        return []
    return sorted(directory.glob("*.md"), reverse=True)


briefings = _list_briefings(DEFAULT_OUTPUT_DIR)

if not briefings:
    st.info("No briefings found. Generate one with `uv run python -m grid_signals briefing`.")
else:
    labels = [p.stem for p in briefings]
    selected = st.selectbox("Select date", labels, index=0)
    if selected:
        path = DEFAULT_OUTPUT_DIR / f"{selected}.md"
        content = path.read_text(encoding="utf-8")
        st.markdown(content)
