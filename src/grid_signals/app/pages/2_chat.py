"""Chat page — ask the energy intelligence agent questions."""

import json
import os
from datetime import date
from pathlib import Path

import duckdb
import streamlit as st

from grid_signals.agent.loop import Agent, AgentResult
from grid_signals.db.connection import DEFAULT_DB_PATH

DAILY_COST_LIMIT_USD = float(os.environ.get("CHAT_DAILY_LIMIT_USD", "5.0"))
_USAGE_FILE = Path("data/chat_usage.json")


def _get_daily_spend() -> float:
    today = date.today().isoformat()
    if _USAGE_FILE.exists():
        data = json.loads(_USAGE_FILE.read_text())
        return data.get(today, 0.0)
    return 0.0


def _record_spend(cost_usd: float) -> None:
    today = date.today().isoformat()
    data: dict = {}
    if _USAGE_FILE.exists():
        data = json.loads(_USAGE_FILE.read_text())
    data[today] = data.get(today, 0.0) + cost_usd
    _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _USAGE_FILE.write_text(json.dumps(data))

st.set_page_config(page_title="Chat — Grid Signals", page_icon="⚡", layout="wide")
st.title("Energy Intelligence Chat")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "api_messages" not in st.session_state:
    st.session_state.api_messages = []

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

# Rate limit check
if _get_daily_spend() >= DAILY_COST_LIMIT_USD:
    st.warning(
        f"Daily LLM spend limit (${DAILY_COST_LIMIT_USD:.2f}) reached. Try again tomorrow."
    )

# Chat input
if prompt := st.chat_input("Ask about Baltic-Nordic energy markets..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    if _get_daily_spend() >= DAILY_COST_LIMIT_USD:
        st.warning(
            f"Daily LLM spend limit (${DAILY_COST_LIMIT_USD:.2f}) reached. Try again tomorrow."
        )
        st.stop()

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            con = get_chat_db()
            agent = Agent(con)
            result: AgentResult = agent.run(
                prompt,
                message_history=st.session_state.api_messages or None,
            )
            _record_spend(result.estimated_cost_usd)

        st.markdown(result.content)

        tool_info = []
        if result.tool_calls:
            with st.expander(f"🔧 {len(result.tool_calls)} tool calls"):
                for tc in result.tool_calls:
                    st.code(f"{tc.name}({tc.input})", language="json")
                    tool_info.append({"name": tc.name, "input": str(tc.input)})

        cost_str = (
            f"Tokens: {result.input_tokens:,} in / {result.output_tokens:,} out · "
            f"Estimated cost: ${result.estimated_cost_usd:.4f}"
        )
        st.caption(cost_str)

    st.session_state.messages.append({
        "role": "assistant",
        "content": result.content,
        "tool_calls": tool_info,
        "cost": cost_str,
    })
    st.session_state.api_messages.extend(result.messages)
