"""Agent conversation loop using Claude API with tool use."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import anthropic
import duckdb

from grid_signals.agent.prompt import SYSTEM_PROMPT
from grid_signals.agent.tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TURNS = 15


@dataclass
class ToolCallRecord:
    """Log entry for a single tool invocation."""

    name: str
    input: dict
    output: str


@dataclass
class AgentResult:
    """Result of an agent run."""

    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def estimated_cost_usd(self) -> float:
        """Estimate API cost in USD based on model and token counts."""
        return estimate_cost(self.model, self.input_tokens, self.output_tokens)


# Pricing per million tokens (input, output) in USD.
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-opus-4-20250514": (15.00, 75.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate API cost in USD. Falls back to Sonnet pricing for unknown models."""
    input_price, output_price = _MODEL_PRICING.get(
        model, _MODEL_PRICING["claude-sonnet-4-20250514"]
    )
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


class Agent:
    """Synchronous agent that wraps Claude API with energy market tools."""

    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        *,
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        max_turns: int = DEFAULT_MAX_TURNS,
    ) -> None:
        self.con = con
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.max_turns = max_turns

    def run(self, user_message: str) -> AgentResult:
        """Run a conversation loop until the model stops or max_turns is hit."""
        messages: list[dict] = [{"role": "user", "content": user_message}]
        tool_log: list[ToolCallRecord] = []
        total_input_tokens = 0
        total_output_tokens = 0

        for turn in range(self.max_turns):
            logger.debug("Turn %d, sending %d messages", turn + 1, len(messages))

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            if response.stop_reason == "end_turn":
                text = _extract_text(response.content)
                return AgentResult(
                    content=text,
                    tool_calls=tool_log,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    model=self.model,
                )

            if response.stop_reason == "tool_use":
                # Append assistant message (contains tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool call and collect results
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info("Tool call: %s(%s)", block.name, block.input)
                        output = execute_tool(block.name, block.input, self.con)
                        logger.debug("Tool result: %s", output[:200])

                        tool_log.append(ToolCallRecord(
                            name=block.name,
                            input=block.input,
                            output=output,
                        ))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — return what we have
            text = _extract_text(response.content)
            return AgentResult(
                content=text or f"[Unexpected stop_reason: {response.stop_reason}]",
                tool_calls=tool_log,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                model=self.model,
            )

        # Max turns exhausted
        return AgentResult(
            content=(
                "[Agent reached the maximum number of turns without completing. "
                "Please try a more specific question.]"
            ),
            tool_calls=tool_log,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            model=self.model,
        )


def _extract_text(content: list) -> str:
    """Extract text from response content blocks."""
    parts = []
    for block in content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)


def run_agent(
    user_message: str,
    con: duckdb.DuckDBPyConnection,
    *,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> AgentResult:
    """Convenience function: create an Agent and run a single message."""
    agent = Agent(con, model=model, max_turns=max_turns)
    return agent.run(user_message)
