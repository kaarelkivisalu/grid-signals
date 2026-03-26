"""Chat page — ask the energy intelligence agent questions."""

import os

import duckdb
import streamlit as st

from grid_signals.agent.loop import Agent, AgentResult
from grid_signals.db.connection import DEFAULT_DB_PATH

st.set_page_config(page_title="Chat — Grid Signals", page_icon="⚡", layout="wide")
st.title("Energy Intelligence Chat")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Check for API key
if not os.environ.get("ANTHROPIC_API_KEY"):
    st.warning("Set ANTHROPIC_API_KEY environment variable to use the chat.")
    st.stop()


@st.cache_resource
def get_chat_db() -> duckdb.DuckDBPyConnection:
    """Read-only DB connection for the chat agent."""
    return duckdb.connect(str(DEFAULT_DB_PATH), read_only=True)


# Display conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "tool_calls" in msg:
            with st.expander(f"🔧 {len(msg['tool_calls'])} tool calls"):
                for tc in msg["tool_calls"]:
                    st.code(f"{tc['name']}({tc['input']})", language="json")
        if "cost" in msg:
            st.caption(msg["cost"])

# Chat input
if prompt := st.chat_input("Ask about Baltic-Nordic energy markets..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            con = get_chat_db()
            agent = Agent(con)
            result: AgentResult = agent.run(prompt)

        st.markdown(result.content)

        tool_info = []
        if result.tool_calls:
            with st.expander(f"🔧 {len(result.tool_calls)} tool calls"):
                for tc in result.tool_calls:
                    st.code(f"{tc.name}({tc.input})", language="json")
                    tool_info.append({"name": tc.name, "input": str(tc.input)})

        cost_str = (
            f"Tokens: {result.input_tokens:,} in / {result.output_tokens:,} out · "
            f"Cost: ${result.estimated_cost_usd:.4f}"
        )
        st.caption(cost_str)

    st.session_state.messages.append({
        "role": "assistant",
        "content": result.content,
        "tool_calls": tool_info,
        "cost": cost_str,
    })
