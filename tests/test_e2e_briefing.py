"""End-to-end test: seed DB → run briefing generation → verify output.

Seeds DuckDB with known data, mocks the Anthropic API to make tool calls
that hit the real database, and verifies the final briefing output
references correct numbers from the seed data.
"""

import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import duckdb
import pytest

from grid_signals.briefing import generate_briefing
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

# ---------------------------------------------------------------------------
# Test data constants
# ---------------------------------------------------------------------------

TARGET_DATE = date(2024, 3, 15)  # Friday

# Known seed values the briefing must reference
EE_AVG_PRICE = 73.0  # 50 + (0+1+...+23)*2/24 = 50 + 23 = 73
FI_AVG_PRICE = 63.0  # 40 + 23 = 63
EE_FI_SPREAD = 10.0  # constant 10 every hour
OUTAGE_ASSET = "Olkiluoto 2"
OUTAGE_MW = 890.0
WIND_SPEED = 8.5


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def con():
    """In-memory DuckDB seeded with known data for 2024-03-15."""
    c = duckdb.connect(":memory:")
    create_tables(c)
    _seed_data(c)
    yield c
    c.close()


def _seed_data(con: duckdb.DuckDBPyConnection) -> None:
    day = datetime(2024, 3, 15, tzinfo=UTC)

    one_hour = timedelta(hours=1)
    cet_tz = ZoneInfo("Europe/Berlin")
    # Prices aligned to CET delivery day 2024-03-15.
    # CET 00:00 = UTC 23:00 on March 14 (March 15 is still CET, UTC+1).
    cet_start = datetime(2024, 3, 15, tzinfo=cet_tz).astimezone(UTC)
    # Prices: EE 50..96, FI 40..86
    insert_day_ahead_prices(
        con,
        [
            DayAheadPrice(
                zone=BiddingZone.EE,
                period_start=cet_start + timedelta(hours=h),
                period_end=cet_start + timedelta(hours=h) + one_hour,
                price_eur_mwh=50.0 + h * 2,
            )
            for h in range(24)
        ],
    )
    insert_day_ahead_prices(
        con,
        [
            DayAheadPrice(
                zone=BiddingZone.FI,
                period_start=cet_start + timedelta(hours=h),
                period_end=cet_start + timedelta(hours=h) + one_hour,
                price_eur_mwh=40.0 + h * 2,
            )
            for h in range(24)
        ],
    )

    # Generation mix
    ts = datetime(2024, 3, 15, 12, tzinfo=UTC)
    insert_generation_by_type(
        con,
        [
            GenerationByType(
                zone=BiddingZone.EE,
                period_start=ts,
                period_end=ts + one_hour,
                fuel_type="oil_shale",
                generation_mw=750.0,
            ),
            GenerationByType(
                zone=BiddingZone.EE,
                period_start=ts,
                period_end=ts + one_hour,
                fuel_type="wind_onshore",
                generation_mw=200.0,
            ),
        ],
    )

    # Load forecast
    insert_total_load(
        con,
        [
            TotalLoad(
                zone=BiddingZone.EE,
                period_start=datetime(2024, 3, 15, h, tzinfo=UTC),
                period_end=datetime(2024, 3, 15, h, tzinfo=UTC) + one_hour,
                load_mw=950.0 + h * 10,
                is_forecast=True,
            )
            for h in range(24)
        ],
    )

    # Cross-border flows FI→EE
    insert_cross_border_flows(
        con,
        [
            CrossBorderFlow(
                from_zone=BiddingZone.FI,
                to_zone=BiddingZone.EE,
                period_start=datetime(2024, 3, 15, h, tzinfo=UTC),
                period_end=datetime(2024, 3, 15, h, tzinfo=UTC) + one_hour,
                flow_mw=500.0,
            )
            for h in range(24)
        ],
    )

    # Outages
    insert_outages(
        con,
        [
            Outage(
                zone=BiddingZone.FI,
                asset_name=OUTAGE_ASSET,
                fuel_type="nuclear",
                outage_type="planned",
                unavailable_mw=OUTAGE_MW,
                period_start=datetime(2024, 3, 10, tzinfo=UTC),
                period_end=datetime(2024, 3, 20, tzinfo=UTC),
                message_id="REMIT-E2E-001",
            ),
        ],
    )

    # Weather: EE_tallinn  # noqa: ERA001
    insert_weather_forecasts(
        con,
        [
            WeatherForecast(
                location_name="EE_tallinn",
                latitude=59.0,
                longitude=25.0,
                period_start=datetime(2024, 3, 15, h, tzinfo=UTC),
                period_end=datetime(2024, 3, 15, h, tzinfo=UTC) + one_hour,
                fetched_at=day,
                wind_speed_100m_ms=WIND_SPEED,
                solar_irradiance_wm2=120.0,
                temperature_c=2.0,
            )
            for h in range(24)
        ],
    )


# ---------------------------------------------------------------------------
# Mock Anthropic API that makes real tool calls
# ---------------------------------------------------------------------------


def _make_text_block(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(tool_id: str, name: str, tool_input: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = tool_input
    return block


def _make_response(content, stop_reason, input_tokens=500, output_tokens=300):
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    resp.usage = MagicMock()
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


FINAL_BRIEFING = f"""\
## Key Signal
Finnish nuclear capacity remains constrained with {OUTAGE_ASSET} ({int(OUTAGE_MW)} MW) \
offline until March 20, keeping FI prices elevated and driving imports via EstLink.

## Price Outlook
Estonian day-ahead prices averaged {EE_AVG_PRICE:.2f} EUR/MWh on March 15, ranging \
from 50.00 to 96.00 EUR/MWh. Finnish prices averaged {FI_AVG_PRICE:.2f} EUR/MWh, \
with FI consistently cheaper than EE by {EE_FI_SPREAD:.2f} EUR/MWh.

## Wind & Weather
Wind speeds at EE_tallinn held steady at {WIND_SPEED} m/s throughout the day, \
above typical March averages. Solar irradiance at 120 W/m2 with temperatures \
around 2.0 degC.

## Outages
{OUTAGE_ASSET} (FI, nuclear, {int(OUTAGE_MW)} MW) — planned outage through March 20. \
No new outage messages.

## Spreads
EE-FI spread was a constant {EE_FI_SPREAD:.2f} EUR/MWh (EE more expensive), \
indicating persistent EstLink congestion. FI→EE flows at 500 MW near \
interconnector capacity.

## Watch List
- {OUTAGE_ASSET} return on March 20 — watch for schedule changes
- Wind forecast evolution for SE4 and FI regions
- EE-FI spread narrowing if FI wind picks up
"""


class TestEndToEndBriefing:
    """Full pipeline: seed DB → agent with tool calls → verify output."""

    def test_briefing_references_correct_data(self, con, tmp_path):
        """The agent makes tool calls against real DB data and produces a briefing.

        Verifies that the briefing references the correct numbers.
        """
        mock_client = MagicMock()

        # Turn 1: agent requests prices for EE and FI, and outages for FI
        turn1 = _make_response(
            content=[
                _make_text_block("Let me gather the data for today's briefing."),
                _make_tool_use_block(
                    "call_1",
                    "get_day_ahead_prices",
                    {
                        "zone": "EE",
                        "start_date": "2024-03-15",
                        "end_date": "2024-03-16",
                    },
                ),
                _make_tool_use_block(
                    "call_2",
                    "get_day_ahead_prices",
                    {
                        "zone": "FI",
                        "start_date": "2024-03-15",
                        "end_date": "2024-03-16",
                    },
                ),
                _make_tool_use_block(
                    "call_3",
                    "get_outages",
                    {"zone": "FI", "active_at": "2024-03-15"},
                ),
            ],
            stop_reason="tool_use",
        )

        # Turn 2: agent requests wind forecast and spreads
        turn2 = _make_response(
            content=[
                _make_tool_use_block(
                    "call_4",
                    "get_wind_forecast",
                    {
                        "location": "EE_tallinn",
                        "start_date": "2024-03-15",
                        "end_date": "2024-03-16",
                    },
                ),
                _make_tool_use_block(
                    "call_5",
                    "calculate_spread",
                    {
                        "zone_1": "EE",
                        "zone_2": "FI",
                        "start_date": "2024-03-15",
                        "end_date": "2024-03-16",
                    },
                ),
            ],
            stop_reason="tool_use",
        )

        # Turn 3: final briefing text
        turn3 = _make_response(
            content=[_make_text_block(FINAL_BRIEFING)],
            stop_reason="end_turn",
        )

        mock_client.messages.create.side_effect = [turn1, turn2, turn3]

        result = generate_briefing(
            con,
            target_date=TARGET_DATE,
            output_dir=tmp_path,
            model="test-model",
            client=mock_client,
        )

        # --- Verify content references correct data ---

        # Prices
        assert "73.00" in result.content  # EE avg price
        assert "63.00" in result.content  # FI avg price
        assert "50.00" in result.content  # EE min price
        assert "96.00" in result.content  # EE max price

        # Spread
        assert "10.00" in result.content  # EE-FI spread

        # Outage
        assert OUTAGE_ASSET in result.content
        assert str(int(OUTAGE_MW)) in result.content

        # Wind
        assert str(WIND_SPEED) in result.content

        # --- Verify file output ---
        output_file = tmp_path / "2024-03-15.md"
        assert output_file.exists()
        file_content = output_file.read_text(encoding="utf-8")
        assert file_content == result.content

        # --- Verify tool call records ---
        assert len(result.agent_result.tool_calls) == 5
        tool_names = [tc.name for tc in result.agent_result.tool_calls]
        assert "get_day_ahead_prices" in tool_names
        assert "get_outages" in tool_names
        assert "get_wind_forecast" in tool_names
        assert "calculate_spread" in tool_names

        # --- Verify tool calls returned real DB data ---
        # EE prices tool call should have daily summary
        ee_price_call = next(
            tc
            for tc in result.agent_result.tool_calls
            if tc.name == "get_day_ahead_prices" and '"EE"' in json.dumps(tc.input)
        )
        ee_data = json.loads(ee_price_call.output)
        assert len(ee_data) >= 1
        # Total intervals across all days should be 24
        total_count = sum(d["count"] for d in ee_data)
        assert total_count == 24
        assert ee_data[0]["min"] == 50.0

        # Outage tool call should find Olkiluoto 2
        outage_call = next(
            tc for tc in result.agent_result.tool_calls if tc.name == "get_outages"
        )
        outage_data = json.loads(outage_call.output)
        assert len(outage_data) == 1
        assert outage_data[0]["asset_name"] == OUTAGE_ASSET

    def test_briefing_sections_present(self, con, tmp_path):
        """Verify the briefing contains all required sections."""
        mock_client = MagicMock()

        # Simple single-turn response with all sections
        mock_client.messages.create.return_value = _make_response(
            content=[_make_text_block(FINAL_BRIEFING)],
            stop_reason="end_turn",
        )

        result = generate_briefing(
            con,
            target_date=TARGET_DATE,
            output_dir=tmp_path,
            model="test-model",
            client=mock_client,
        )

        assert "## Key Signal" in result.content
        assert "## Price Outlook" in result.content
        assert "## Wind & Weather" in result.content
        assert "## Outages" in result.content
        assert "## Spreads" in result.content
        assert "## Watch List" in result.content
