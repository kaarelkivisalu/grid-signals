"""Tests for the LLM agent: tool execution (real DB) and loop (mocked API)."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import duckdb
import pytest

from grid_signals.agent.loop import Agent, AgentResult
from grid_signals.agent.tools import execute_tool
from grid_signals.db.queries import (
    insert_cross_border_flows,
    insert_day_ahead_prices,
    insert_generation_by_type,
    insert_outages,
    insert_total_load,
    insert_weather_forecasts,
)
from grid_signals.db.schema import create_tables
from grid_signals.models import (
    BiddingZone,
    CrossBorderFlow,
    DayAheadPrice,
    GenerationByType,
    Outage,
    TotalLoad,
    WeatherForecast,
)

_1H = timedelta(hours=1)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def con():
    """In-memory DuckDB with tables and seed data."""
    c = duckdb.connect(":memory:")
    create_tables(c)
    _seed_data(c)
    yield c
    c.close()


def _seed_data(con: duckdb.DuckDBPyConnection) -> None:
    """Insert known data for 2024-01-15 across multiple tables."""
    day = datetime(2024, 1, 15, tzinfo=UTC)

    # Prices: EE and FI for 24 hours
    ee_prices = [
        DayAheadPrice(
            zone=BiddingZone.EE,
            period_start=datetime(2024, 1, 15, h, tzinfo=UTC),
            period_end=datetime(2024, 1, 15, h, tzinfo=UTC) + _1H,
            price_eur_mwh=50.0 + h * 2,  # 50, 52, 54, ... 96
        )
        for h in range(24)
    ]
    fi_prices = [
        DayAheadPrice(
            zone=BiddingZone.FI,
            period_start=datetime(2024, 1, 15, h, tzinfo=UTC),
            period_end=datetime(2024, 1, 15, h, tzinfo=UTC) + _1H,
            price_eur_mwh=40.0 + h * 2,  # 40, 42, 44, ... 86
        )
        for h in range(24)
    ]
    insert_day_ahead_prices(con, ee_prices)
    insert_day_ahead_prices(con, fi_prices)

    # Generation mix for EE
    ts = datetime(2024, 1, 15, 12, tzinfo=UTC)
    insert_generation_by_type(con, [
        GenerationByType(
            zone=BiddingZone.EE,
            period_start=ts,
            period_end=ts + _1H,
            fuel_type="oil_shale",
            generation_mw=800.0,
        ),
        GenerationByType(
            zone=BiddingZone.EE,
            period_start=ts,
            period_end=ts + _1H,
            fuel_type="wind_onshore",
            generation_mw=150.0,
        ),
    ])

    # Total load (forecast) for EE
    insert_total_load(con, [
        TotalLoad(
            zone=BiddingZone.EE,
            period_start=datetime(2024, 1, 15, h, tzinfo=UTC),
            period_end=datetime(2024, 1, 15, h, tzinfo=UTC) + _1H,
            load_mw=900.0 + h * 10,
            is_forecast=True,
        )
        for h in range(24)
    ])

    # Cross-border flows FI->EE
    ts2 = datetime(2024, 1, 15, 12, tzinfo=UTC)
    insert_cross_border_flows(con, [
        CrossBorderFlow(
            from_zone=BiddingZone.FI,
            to_zone=BiddingZone.EE,
            period_start=ts2,
            period_end=ts2 + _1H,
            flow_mw=450.0,
        ),
    ])

    # Outages
    insert_outages(con, [
        Outage(
            zone=BiddingZone.FI,
            asset_name="Olkiluoto 2",
            fuel_type="nuclear",
            outage_type="planned",
            unavailable_mw=890.0,
            period_start=datetime(2024, 1, 10, tzinfo=UTC),
            period_end=datetime(2024, 1, 20, tzinfo=UTC),
            message_id="REMIT-TEST-001",
        ),
    ])

    # Weather for EE_tallinn — two days for similar-day matching
    for d in [15, 16]:
        insert_weather_forecasts(con, [
            WeatherForecast(
                location_name="EE_tallinn",
                latitude=59.0,
                longitude=25.0,
                period_start=datetime(2024, 1, d, h, tzinfo=UTC),
                period_end=datetime(2024, 1, d, h, tzinfo=UTC) + _1H,
                fetched_at=day,
                wind_speed_100m_ms=7.0 + (d - 15) * 0.5,
                solar_irradiance_wm2=50.0,
                temperature_c=-5.0 + (d - 15) * 1.0,
            )
            for h in range(24)
        ])

    # Extra day of prices for Jan 16 (for similar-day test)
    insert_day_ahead_prices(con, [
        DayAheadPrice(
            zone=BiddingZone.EE,
            period_start=datetime(2024, 1, 16, h, tzinfo=UTC),
            period_end=datetime(2024, 1, 16, h, tzinfo=UTC) + _1H,
            price_eur_mwh=55.0 + h * 2,
        )
        for h in range(24)
    ])


# ---------------------------------------------------------------------------
# Tool execution tests (real DuckDB, no mocks)
# ---------------------------------------------------------------------------


class TestGetDayAheadPrices:
    def test_returns_prices(self, con):
        result = json.loads(execute_tool(
            "get_day_ahead_prices",
            {"zone": "EE", "start_date": "2024-01-15", "end_date": "2024-01-16"},
            con,
        ))
        assert len(result) == 24
        assert result[0]["price_eur_mwh"] == 50.0
        assert result[23]["price_eur_mwh"] == 96.0

    def test_empty_range(self, con):
        result = json.loads(execute_tool(
            "get_day_ahead_prices",
            {"zone": "EE", "start_date": "2025-01-01", "end_date": "2025-01-02"},
            con,
        ))
        assert result == []

    def test_invalid_zone(self, con):
        result = json.loads(execute_tool(
            "get_day_ahead_prices",
            {"zone": "INVALID", "start_date": "2024-01-15", "end_date": "2024-01-16"},
            con,
        ))
        assert "error" in result


class TestGetGenerationMix:
    def test_returns_all_types(self, con):
        result = json.loads(execute_tool(
            "get_generation_mix",
            {"zone": "EE", "start_date": "2024-01-15", "end_date": "2024-01-16"},
            con,
        ))
        assert len(result) == 2
        fuel_types = {r["fuel_type"] for r in result}
        assert fuel_types == {"oil_shale", "wind_onshore"}

    def test_filter_by_fuel_type(self, con):
        result = json.loads(execute_tool(
            "get_generation_mix",
            {
                "zone": "EE",
                "start_date": "2024-01-15",
                "end_date": "2024-01-16",
                "fuel_type": "wind_onshore",
            },
            con,
        ))
        assert len(result) == 1
        assert result[0]["generation_mw"] == 150.0


class TestGetWindForecast:
    def test_returns_forecasts(self, con):
        result = json.loads(execute_tool(
            "get_wind_forecast",
            {"location": "EE_tallinn", "start_date": "2024-01-15", "end_date": "2024-01-16"},
            con,
        ))
        assert len(result) == 24
        assert result[0]["wind_speed_100m_ms"] == 7.0

    def test_unknown_location(self, con):
        result = json.loads(execute_tool(
            "get_wind_forecast",
            {"location": "NOWHERE", "start_date": "2024-01-15", "end_date": "2024-01-16"},
            con,
        ))
        assert result == []


class TestGetOutages:
    def test_returns_outages(self, con):
        result = json.loads(execute_tool("get_outages", {"zone": "FI"}, con))
        assert len(result) == 1
        assert result[0]["asset_name"] == "Olkiluoto 2"

    def test_filter_by_active_at(self, con):
        result = json.loads(execute_tool(
            "get_outages",
            {"zone": "FI", "active_at": "2024-01-15"},
            con,
        ))
        assert len(result) == 1

        result = json.loads(execute_tool(
            "get_outages",
            {"zone": "FI", "active_at": "2024-02-01"},
            con,
        ))
        assert len(result) == 0

    def test_no_outages(self, con):
        result = json.loads(execute_tool("get_outages", {"zone": "LT"}, con))
        assert result == []


class TestGetCrossBorderFlows:
    def test_returns_flows(self, con):
        result = json.loads(execute_tool(
            "get_cross_border_flows",
            {
                "from_zone": "FI",
                "to_zone": "EE",
                "start_date": "2024-01-15",
                "end_date": "2024-01-16",
            },
            con,
        ))
        assert len(result) == 1
        assert result[0]["flow_mw"] == 450.0


class TestGetLoadForecast:
    def test_returns_forecast_only(self, con):
        result = json.loads(execute_tool(
            "get_load_forecast",
            {"zone": "EE", "start_date": "2024-01-15", "end_date": "2024-01-16"},
            con,
        ))
        assert len(result) == 24
        assert all(r["is_forecast"] for r in result)


class TestCalculateSpread:
    def test_spread_arithmetic(self, con):
        result = json.loads(execute_tool(
            "calculate_spread",
            {
                "zone_1": "EE",
                "zone_2": "FI",
                "start_date": "2024-01-15",
                "end_date": "2024-01-16",
            },
            con,
        ))
        assert result["zone_1"] == "EE"
        assert result["zone_2"] == "FI"
        assert len(result["hourly"]) == 24
        # EE = 50+h*2, FI = 40+h*2 → spread = 10 for every hour
        for h in result["hourly"]:
            assert h["spread"] == 10.0
        assert result["summary"]["mean_spread"] == 10.0
        assert result["summary"]["hours_positive"] == 24
        assert result["summary"]["hours_negative"] == 0

    def test_spread_empty(self, con):
        result = json.loads(execute_tool(
            "calculate_spread",
            {
                "zone_1": "LV",
                "zone_2": "LT",
                "start_date": "2024-01-15",
                "end_date": "2024-01-16",
            },
            con,
        ))
        assert result["hourly"] == []
        assert result["summary"] is None


class TestGetHistoricalSimilarDays:
    def test_finds_similar_days(self, con):
        # Jan 15 weather: wind=7.0, temp=-5.0
        # Jan 16 weather: wind=7.5, temp=-4.0
        result = json.loads(execute_tool(
            "get_historical_similar_days",
            {
                "zone": "EE",
                "location": "EE_tallinn",
                "target_wind_ms": 7.0,
                "target_temp_c": -5.0,
                "wind_tolerance_ms": 1.0,
                "temp_tolerance_c": 2.0,
            },
            con,
        ))
        assert result["matching_days"] >= 1
        # Jan 15 should definitely match (exact hit)
        dates = [d["date"] for d in result["days"]]
        assert any("2024-01-15" in d for d in dates)

    def test_no_matches(self, con):
        result = json.loads(execute_tool(
            "get_historical_similar_days",
            {
                "zone": "EE",
                "location": "EE_tallinn",
                "target_wind_ms": 30.0,
                "target_temp_c": 40.0,
                "wind_tolerance_ms": 0.1,
                "temp_tolerance_c": 0.1,
            },
            con,
        ))
        assert result["matching_days"] == 0
        assert result["days"] == []


class TestUnknownTool:
    def test_error_json(self, con):
        result = json.loads(execute_tool("nonexistent_tool", {}, con))
        assert "error" in result
        assert "Unknown tool" in result["error"]


# ---------------------------------------------------------------------------
# Agent loop tests (mocked Anthropic client)
# ---------------------------------------------------------------------------


def _make_text_block(text: str):
    """Create a mock text content block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(tool_id: str, name: str, tool_input: dict):
    """Create a mock tool_use content block."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = tool_input
    return block


def _make_response(content, stop_reason: str, input_tokens: int = 10, output_tokens: int = 20):
    """Create a mock API response."""
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    resp.usage = MagicMock()
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


class TestAgentLoopSimpleResponse:
    def test_returns_text_without_tools(self, con):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_response(
            content=[_make_text_block("The available bidding zones are EE, LV, LT, FI, SE4, SE3.")],
            stop_reason="end_turn",
        )

        agent = Agent(con, client=mock_client, model="test-model")
        result = agent.run("What zones are available?")

        assert "EE" in result.content
        assert result.tool_calls == []
        assert result.input_tokens == 10
        assert result.output_tokens == 20


class TestAgentLoopSingleToolCall:
    def test_calls_tool_and_returns(self, con):
        mock_client = MagicMock()

        # First call: model wants to use a tool
        tool_response = _make_response(
            content=[
                _make_text_block("Let me look up the prices."),
                _make_tool_use_block(
                    "call_1",
                    "get_day_ahead_prices",
                    {"zone": "EE", "start_date": "2024-01-15", "end_date": "2024-01-16"},
                ),
            ],
            stop_reason="tool_use",
        )

        # Second call: model produces final text
        final_response = _make_response(
            content=[_make_text_block("EE prices on Jan 15 ranged from 50 to 96 EUR/MWh.")],
            stop_reason="end_turn",
        )

        mock_client.messages.create.side_effect = [tool_response, final_response]

        agent = Agent(con, client=mock_client, model="test-model")
        result = agent.run("What were EE prices on Jan 15?")

        assert "50" in result.content or "96" in result.content
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_day_ahead_prices"
        # Verify the tool got real data from the DB
        tool_output = json.loads(result.tool_calls[0].output)
        assert len(tool_output) == 24


class TestAgentLoopMultipleToolCalls:
    def test_handles_parallel_tool_calls(self, con):
        mock_client = MagicMock()

        # Model requests two tools at once
        tool_response = _make_response(
            content=[
                _make_tool_use_block(
                    "call_1",
                    "get_day_ahead_prices",
                    {"zone": "EE", "start_date": "2024-01-15", "end_date": "2024-01-16"},
                ),
                _make_tool_use_block(
                    "call_2",
                    "get_day_ahead_prices",
                    {"zone": "FI", "start_date": "2024-01-15", "end_date": "2024-01-16"},
                ),
            ],
            stop_reason="tool_use",
        )

        final_response = _make_response(
            content=[_make_text_block("EE was 10 EUR/MWh more expensive than FI.")],
            stop_reason="end_turn",
        )

        mock_client.messages.create.side_effect = [tool_response, final_response]

        agent = Agent(con, client=mock_client, model="test-model")
        result = agent.run("Compare EE and FI prices")

        assert len(result.tool_calls) == 2
        assert result.input_tokens == 20  # 10 + 10
        assert result.output_tokens == 40  # 20 + 20


class TestAgentLoopMaxTurns:
    def test_stops_at_max_turns(self, con):
        mock_client = MagicMock()

        # Every response asks for another tool call
        def always_tool_use(**kwargs):
            return _make_response(
                content=[
                    _make_tool_use_block(
                        "call_loop",
                        "get_day_ahead_prices",
                        {"zone": "EE", "start_date": "2024-01-15", "end_date": "2024-01-16"},
                    ),
                ],
                stop_reason="tool_use",
            )

        mock_client.messages.create.side_effect = always_tool_use

        agent = Agent(con, client=mock_client, model="test-model", max_turns=3)
        result = agent.run("Keep going forever")

        assert "maximum number of turns" in result.content
        assert len(result.tool_calls) == 3
