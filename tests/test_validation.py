"""Tests for validation and gap detection."""

from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from grid_signals.db.queries import (
    insert_cross_border_flows,
    insert_day_ahead_prices,
    insert_generation_by_type,
    insert_total_load,
)
from grid_signals.db.schema import create_tables
from grid_signals.models import (
    BiddingZone,
    CrossBorderFlow,
    DayAheadPrice,
    GenerationByType,
    TotalLoad,
)
from grid_signals.validation import (
    DataGaps,
    find_gaps,
    run_all_validations,
)

_1H = timedelta(hours=1)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    create_tables(c)
    yield c
    c.close()


def _make_hourly_prices(zone: BiddingZone, day: datetime) -> list[DayAheadPrice]:
    """Generate 24 hourly price rows for a given zone/day."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        DayAheadPrice(
            zone=zone,
            period_start=start + timedelta(hours=h),
            period_end=start + timedelta(hours=h + 1),
            price_eur_mwh=50.0 + h,
        )
        for h in range(24)
    ]


# ---- run_all_validations with date range ----


def test_validate_date_range(con):
    """Validation over a multi-day range checks each day."""
    day1 = datetime(2024, 1, 15, tzinfo=UTC)
    end = datetime(2024, 1, 17, tzinfo=UTC)

    # Insert prices only for day1, not day2
    insert_day_ahead_prices(con, _make_hourly_prices(BiddingZone.EE, day1))

    results = run_all_validations(con, start=day1, end=end)

    # day1 EE should pass completeness, day2 EE should fail
    price_checks = [r for r in results if r.check.startswith("price_completeness:EE")]
    assert len(price_checks) == 2
    assert price_checks[0].passed  # day1
    assert not price_checks[1].passed  # day2


def test_validate_defaults_to_yesterday(con):
    """Without start/end, validation checks yesterday."""
    results = run_all_validations(con)
    # Should have results (will all fail since DB is empty, but shouldn't crash)
    assert len(results) > 0


# ---- gap detection ----


def test_find_gaps_empty_db(con):
    """All dates should be gaps when DB is empty."""
    start = datetime(2024, 1, 15, tzinfo=UTC)
    end = datetime(2024, 1, 17, tzinfo=UTC)

    gaps = find_gaps(con, start, end, borders=[("EE", "FI")])

    # Every zone should have both dates missing for prices
    assert BiddingZone.EE.value in gaps.prices
    assert len(gaps.prices[BiddingZone.EE.value]) == 2
    assert not gaps.empty


def test_find_gaps_no_gaps(con):
    """No gaps when all data is present."""
    start = datetime(2024, 1, 15, tzinfo=UTC)
    end = datetime(2024, 1, 16, tzinfo=UTC)
    day = datetime(2024, 1, 15, tzinfo=UTC)

    # Insert prices for all zones
    for zone in BiddingZone:
        insert_day_ahead_prices(con, _make_hourly_prices(zone, day))

    # Insert generation for all zones
    gen_start = day.replace(hour=0)
    for zone in BiddingZone:
        insert_generation_by_type(
            con,
            [
                GenerationByType(
                    zone=zone,
                    fuel_type="wind_onshore",
                    period_start=gen_start,
                    period_end=gen_start + _1H,
                    generation_mw=100.0,
                )
            ],
        )

    # Insert load for all zones
    for zone in BiddingZone:
        insert_total_load(
            con,
            [
                TotalLoad(
                    zone=zone,
                    period_start=gen_start,
                    period_end=gen_start + _1H,
                    load_mw=500.0,
                    is_forecast=False,
                )
            ],
        )

    # Insert flows for our test border
    insert_cross_border_flows(
        con,
        [
            CrossBorderFlow(
                from_zone="EE",
                to_zone="FI",
                period_start=gen_start,
                period_end=gen_start + _1H,
                flow_mw=200.0,
            )
        ],
    )

    gaps = find_gaps(con, start, end, borders=[("EE", "FI")])
    assert gaps.prices == {}
    assert gaps.generation == {}
    assert gaps.load == {}
    assert gaps.flows == {}
    assert gaps.empty


def test_find_gaps_partial(con):
    """Detect gaps only for zones/dates missing data."""
    from datetime import date as date_type

    start = datetime(2024, 1, 15, tzinfo=UTC)
    end = datetime(2024, 1, 18, tzinfo=UTC)
    day1 = datetime(2024, 1, 15, tzinfo=UTC)

    # Insert prices for EE on day1 only (24 hours)
    insert_day_ahead_prices(con, _make_hourly_prices(BiddingZone.EE, day1))

    gaps = find_gaps(con, start, end, borders=[])

    # EE has data for Jan 15 (and possibly Jan 16 due to TZ),
    # but should be missing at least Jan 17
    assert date_type(2024, 1, 17) in gaps.prices.get(BiddingZone.EE.value, [])

    # LV should have all three days missing
    assert len(gaps.prices[BiddingZone.LV.value]) == 3


def test_find_gaps_flow_detection(con):
    """Detect gaps in cross-border flow data."""
    start = datetime(2024, 1, 15, tzinfo=UTC)
    end = datetime(2024, 1, 16, tzinfo=UTC)
    day = datetime(2024, 1, 15, tzinfo=UTC)

    # Insert flow for EE→FI but not FI→EE
    insert_cross_border_flows(
        con,
        [
            CrossBorderFlow(
                from_zone="EE",
                to_zone="FI",
                period_start=day,
                period_end=day + _1H,
                flow_mw=100.0,
            )
        ],
    )

    gaps = find_gaps(con, start, end, borders=[("EE", "FI"), ("FI", "EE")])
    assert "EE→FI" not in gaps.flows
    assert "FI→EE" in gaps.flows


def test_data_gaps_summary():
    """Summary string is human-readable."""
    from datetime import date

    gaps = DataGaps(
        prices={"EE": [date(2024, 1, 15), date(2024, 1, 16)]},
        generation={},
        load={"EE": [date(2024, 1, 15)]},
        flows={},
    )
    summary = gaps.summary()
    assert "prices" in summary
    assert "load" in summary
    assert "generation" not in summary  # no generation gaps


def test_data_gaps_empty():
    gaps = DataGaps(prices={}, generation={}, load={}, flows={})
    assert gaps.empty
    assert gaps.summary() == "No gaps found."
