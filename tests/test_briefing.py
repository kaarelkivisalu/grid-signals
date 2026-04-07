"""Tests for the daily briefing generation module."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from grid_signals.agent.loop import AgentResult
from grid_signals.briefing import (
    BriefingResult,
    build_briefing_prompt,
    generate_briefing,
)
from grid_signals.db.queries import get_briefing, insert_day_ahead_prices
from grid_signals.models import BiddingZone, DayAheadPrice

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def con(con):
    """PostgreSQL connection seeded with minimal price data."""
    insert_day_ahead_prices(
        con,
        [
            DayAheadPrice(
                zone=BiddingZone.EE,
                period_start=datetime(2024, 6, 10, h, tzinfo=UTC),
                period_end=datetime(2024, 6, 10, h, tzinfo=UTC) + timedelta(hours=1),
                price_eur_mwh=45.0 + h,
            )
            for h in range(24)
        ],
    )
    return con


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestBuildBriefingPrompt:
    def test_includes_date(self):
        prompt = build_briefing_prompt(date(2024, 6, 10))
        assert "2024-06-10" in prompt
        assert "Monday" in prompt

    def test_includes_sections(self):
        prompt = build_briefing_prompt(date(2024, 1, 1))
        assert "## Key Signal" in prompt
        assert "## Price Outlook" in prompt
        assert "## Wind & Weather" in prompt
        assert "## Outages" in prompt
        assert "## Spreads" in prompt
        assert "## Watch List" in prompt

    def test_weekend(self):
        prompt = build_briefing_prompt(date(2024, 6, 15))  # Saturday
        assert "Saturday" in prompt


# ---------------------------------------------------------------------------
# Briefing generation (mocked agent)
# ---------------------------------------------------------------------------


def _mock_agent_run(content: str):
    """Create a mock Agent whose run() returns a canned AgentResult."""
    mock_agent_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.run.return_value = AgentResult(
        content=content,
        tool_calls=[],
        input_tokens=100,
        output_tokens=200,
    )
    mock_agent_cls.return_value = mock_instance
    return mock_agent_cls


SAMPLE_BRIEFING = """\
## Key Signal
Estonian prices are elevated due to low wind and Narva maintenance.

## Price Outlook
EE day-ahead prices averaged 65.50 EUR/MWh, up from 52.30 yesterday.

## Wind & Weather
Wind speeds in SE4 at 3.2 m/s, well below the 7.0 m/s weekly average.

## Outages
Olkiluoto 2 (890 MW nuclear) remains offline until Jan 20.

## Spreads
FI-EE spread averaged 10.00 EUR/MWh (FI cheaper), indicating EstLink congestion.

## Watch List
- Olkiluoto 2 return date — any delay extends FI price support
- Wind forecast revision for SE4 expected this afternoon
- NO1-SE3 spread widening as Norwegian hydro reservoirs draw down
"""


class TestGenerateBriefing:
    def test_returns_briefing_result(self, con, monkeypatch):
        monkeypatch.setattr(
            "grid_signals.briefing.Agent",
            _mock_agent_run(SAMPLE_BRIEFING),
        )
        result = generate_briefing(
            con,
            target_date=date(2024, 6, 10),
        )
        assert isinstance(result, BriefingResult)
        assert result.content == SAMPLE_BRIEFING
        assert result.date == date(2024, 6, 10)
        assert result.agent_result.input_tokens == 100

    def test_saves_to_database(self, con, monkeypatch):
        monkeypatch.setattr(
            "grid_signals.briefing.Agent",
            _mock_agent_run(SAMPLE_BRIEFING),
        )
        generate_briefing(
            con,
            target_date=date(2024, 6, 10),
        )
        row = get_briefing(con, date(2024, 6, 10))
        assert row is not None
        content, created_at = row
        assert content == SAMPLE_BRIEFING
        assert created_at is not None

    def test_upsert_overwrites(self, con, monkeypatch):
        monkeypatch.setattr(
            "grid_signals.briefing.Agent",
            _mock_agent_run("first version"),
        )
        generate_briefing(con, target_date=date(2024, 6, 10))

        monkeypatch.setattr(
            "grid_signals.briefing.Agent",
            _mock_agent_run("second version"),
        )
        generate_briefing(con, target_date=date(2024, 6, 10))

        row = get_briefing(con, date(2024, 6, 10))
        assert row is not None
        assert row[0] == "second version"

    def test_defaults_to_today(self, con, monkeypatch):
        monkeypatch.setattr(
            "grid_signals.briefing.Agent",
            _mock_agent_run("briefing content"),
        )
        result = generate_briefing(con)

        assert result.date == datetime.now(UTC).date()

    def test_passes_prompt_with_date(self, con, monkeypatch):
        mock_cls = _mock_agent_run("content")
        monkeypatch.setattr("grid_signals.briefing.Agent", mock_cls)

        generate_briefing(
            con,
            target_date=date(2024, 6, 10),
        )

        # Check that run() was called with a prompt containing the date
        mock_instance = mock_cls.return_value
        call_args = mock_instance.run.call_args[0][0]
        assert "2024-06-10" in call_args
        assert "Monday" in call_args
