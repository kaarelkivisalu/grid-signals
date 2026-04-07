"""Daily briefing generation: structured morning briefing from the LLM agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anthropic
    import psycopg

from grid_signals.agent.loop import DEFAULT_MAX_TURNS, DEFAULT_MODEL, Agent, AgentResult

logger = logging.getLogger(__name__)

BRIEFING_PROMPT_TEMPLATE = """\
Generate a morning briefing for Baltic-Nordic day-ahead electricity trading.

Today is {date} ({weekday}).

Autonomously decide which tools to call based on what data is available and \
what is most relevant. At minimum, check prices, wind forecasts, and outages \
for the key zones (EE, FI, LT, LV, SE4, NO1, DK1). Also check cross-border spreads \
for the main interconnectors (FI-EE, SE4-LT, EE-LV, NO1-SE3, DK1-DK2).

Structure your briefing with the following sections:

## Key Signal
The single most important thing a trader should know today. One paragraph.

## Price Outlook
Day-ahead price levels and drivers across Baltic-Nordic zones. Compare today \
vs yesterday. Highlight any unusual price levels or divergences between zones.

## Wind & Weather
Wind forecast for key regions and how it compares to recent days. Note any \
significant changes in the forecast that could affect generation.

## Outages
Active or upcoming REMIT outage messages. Highlight any new outages or \
returns from maintenance that affect prices.

## Spreads
Cross-border price spread analysis for key interconnectors (FI-EE, SE4-LT, \
EE-LV, NO1-SE3, DK1-DK2, NO2-DK1). Note congestion patterns.

## Watch List
2-4 bullet points of things to monitor during the day — upcoming events, \
forecast changes, or risks.

Keep the briefing concise and data-driven. Every number must come from a \
tool call. If data is unavailable for a section, note that briefly and \
move on.
"""


@dataclass
class BriefingResult:
    """Result of a briefing generation run."""

    content: str
    date: date
    agent_result: AgentResult


def build_briefing_prompt(target_date: date) -> str:
    """Build the briefing prompt for a given date."""
    weekday = target_date.strftime("%A")
    return BRIEFING_PROMPT_TEMPLATE.format(
        date=target_date.isoformat(), weekday=weekday
    )


def generate_briefing(
    con: psycopg.Connection,
    *,
    target_date: date | None = None,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    client: anthropic.Anthropic | None = None,
    validate_first: bool = True,
) -> BriefingResult:
    """Generate a daily briefing by running the agent with a structured prompt.

    The briefing is saved to the ``briefings`` table in PostgreSQL.

    Args:
        con: PostgreSQL connection with energy data.
        target_date: Date to generate the briefing for (defaults to today UTC).
        model: Claude model to use.
        max_turns: Maximum agent turns.
        client: Anthropic client (optional, for testing).
        validate_first: Run data validation before generating (default True).

    Returns:
        BriefingResult with the briefing content and metadata.
    """
    if target_date is None:
        target_date = datetime.now(UTC).date()

    prompt = build_briefing_prompt(target_date)
    logger.info("Generating briefing for %s", target_date.isoformat())

    if validate_first:
        from grid_signals.validation import run_all_validations

        results = run_all_validations(con)
        failures = [r for r in results if not r.passed]
        if failures:
            logger.warning(
                "Data validation found %d issue(s) before briefing generation",
                len(failures),
            )

    agent = Agent(con, client=client, model=model, max_turns=max_turns)
    agent_result = agent.run(prompt)

    logger.info(
        "Briefing generated: %d chars, %d tool calls, %d/%d tokens, cost: $%.4f",
        len(agent_result.content),
        len(agent_result.tool_calls),
        agent_result.input_tokens,
        agent_result.output_tokens,
        agent_result.estimated_cost_usd,
    )

    # Persist to database
    from grid_signals.db.queries import upsert_briefing

    upsert_briefing(
        con,
        briefing_date=target_date,
        content=agent_result.content,
        model=model,
        input_tokens=agent_result.input_tokens,
        output_tokens=agent_result.output_tokens,
        tool_calls=len(agent_result.tool_calls),
        cost_usd=agent_result.estimated_cost_usd,
    )
    logger.info("Briefing saved to database for %s", target_date.isoformat())

    return BriefingResult(
        content=agent_result.content,
        date=target_date,
        agent_result=agent_result,
    )
