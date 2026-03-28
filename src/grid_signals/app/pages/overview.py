"""Overview page — landing page for Grid Signals."""

import streamlit as st

st.title("Grid Signals")
st.markdown(
    "Nordic-Baltic energy intelligence agent. "
    "Use the sidebar to navigate between pages."
)
st.markdown("""
### Pages

- **Briefings** — View saved daily briefings
- **Chat** — Ask the energy intelligence agent questions
- **Dashboard** — Interactive price, generation, and weather charts
""")
