"""Tests for DB schema creation and data access layer."""

from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from grid_signals.db.schema import create_tables
from grid_signals.db.queries import (
    get_cross_border_flows,
    get_day_ahead_prices,
    get_generation_mix,
    get_outages,
    get_total_load,
    get_weather_forecasts,
    insert_cross_border_flows,
    insert_day_ahead_prices,
    insert_generation_by_type,
    insert_outages,
    insert_total_load,
    insert_weather_forecasts,
)
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


@pytest.fixture
def con():
    """In-memory DuckDB with all tables created."""
    c = duckdb.connect(":memory:")
    create_tables(c)
    yield c
    c.close()


# ---- schema ----


def test_create_tables_idempotent(con):
    """Calling create_tables twice doesn't raise."""
    create_tables(con)


def test_all_tables_exist(con):
    tables = {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    expected = {
        "day_ahead_prices",
        "generation_by_type",
        "total_load",
        "cross_border_flows",
        "outages",
        "weather_forecasts",
    }
    assert expected <= tables


# ---- day-ahead prices ----


def test_insert_and_query_day_ahead_prices(con):
    rows = [
        DayAheadPrice(
            zone=BiddingZone.EE,
            period_start=datetime(2024, 1, 1, h, tzinfo=UTC),
            period_end=datetime(2024, 1, 1, h, tzinfo=UTC) + _1H,
            price_eur_mwh=50.0 + h,
        )
        for h in range(24)
    ]
    assert insert_day_ahead_prices(con, rows) == 24

    result = get_day_ahead_prices(
        con, BiddingZone.EE,
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
    )
    assert len(result) == 24
    assert result[0].price_eur_mwh == 50.0
    assert result[23].price_eur_mwh == 73.0


def test_upsert_day_ahead_prices(con):
    ts = datetime(2024, 1, 1, 12, tzinfo=UTC)
    insert_day_ahead_prices(con, [DayAheadPrice(zone=BiddingZone.FI, period_start=ts, period_end=ts + _1H, price_eur_mwh=40.0)])
    insert_day_ahead_prices(con, [DayAheadPrice(zone=BiddingZone.FI, period_start=ts, period_end=ts + _1H, price_eur_mwh=42.0)])

    result = get_day_ahead_prices(con, BiddingZone.FI, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
    assert len(result) == 1
    assert result[0].price_eur_mwh == 42.0


# ---- generation ----


def test_insert_and_query_generation(con):
    ts = datetime(2024, 6, 15, 12, tzinfo=UTC)
    rows = [
        GenerationByType(zone=BiddingZone.EE, period_start=ts, period_end=ts + _1H, fuel_type="wind_onshore", generation_mw=320.0),
        GenerationByType(zone=BiddingZone.EE, period_start=ts, period_end=ts + _1H, fuel_type="oil_shale", generation_mw=800.0),
    ]
    insert_generation_by_type(con, rows)

    result = get_generation_mix(con, BiddingZone.EE, datetime(2024, 6, 15, tzinfo=UTC), datetime(2024, 6, 16, tzinfo=UTC))
    assert len(result) == 2

    wind_only = get_generation_mix(con, BiddingZone.EE, datetime(2024, 6, 15, tzinfo=UTC), datetime(2024, 6, 16, tzinfo=UTC), fuel_type="wind_onshore")
    assert len(wind_only) == 1
    assert wind_only[0].generation_mw == 320.0


# ---- total load ----


def test_insert_and_query_total_load(con):
    ts = datetime(2024, 1, 1, 8, tzinfo=UTC)
    rows = [
        TotalLoad(zone=BiddingZone.LT, period_start=ts, period_end=ts + _1H, load_mw=1200.0, is_forecast=True),
        TotalLoad(zone=BiddingZone.LT, period_start=ts, period_end=ts + _1H, load_mw=1180.0, is_forecast=False),
    ]
    insert_total_load(con, rows)

    all_rows = get_total_load(con, BiddingZone.LT, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
    assert len(all_rows) == 2

    fc_only = get_total_load(con, BiddingZone.LT, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC), forecast_only=True)
    assert len(fc_only) == 1
    assert fc_only[0].load_mw == 1200.0


# ---- cross-border flows ----


def test_insert_and_query_flows(con):
    ts = datetime(2024, 3, 1, 10, tzinfo=UTC)
    insert_cross_border_flows(con, [
        CrossBorderFlow(from_zone=BiddingZone.FI, to_zone=BiddingZone.EE, period_start=ts, period_end=ts + _1H, flow_mw=450.0),
    ])

    result = get_cross_border_flows(
        con, BiddingZone.FI, BiddingZone.EE,
        datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 2, tzinfo=UTC),
    )
    assert len(result) == 1
    assert result[0].flow_mw == 450.0


# ---- outages ----


def test_insert_and_query_outages(con):
    insert_outages(con, [
        Outage(
            zone=BiddingZone.FI, asset_name="Olkiluoto 2", fuel_type="nuclear",
            outage_type="planned", unavailable_mw=890.0,
            period_start=datetime(2024, 5, 1, tzinfo=UTC),
            period_end=datetime(2024, 5, 15, tzinfo=UTC),
            message_id="REMIT-001",
        ),
        Outage(
            zone=BiddingZone.EE, asset_name="Narva Unit 8", fuel_type="oil_shale",
            outage_type="unplanned", unavailable_mw=300.0,
            period_start=datetime(2024, 5, 3, tzinfo=UTC),
            period_end=None,
            message_id="REMIT-002",
        ),
    ])

    fi_outages = get_outages(con, BiddingZone.FI)
    assert len(fi_outages) == 1
    assert fi_outages[0].asset_name == "Olkiluoto 2"

    active = get_outages(con, BiddingZone.EE, active_at=datetime(2024, 5, 10, tzinfo=UTC))
    assert len(active) == 1
    assert active[0].message_id == "REMIT-002"

    nuclear = get_outages(con, BiddingZone.FI, fuel_type="nuclear")
    assert len(nuclear) == 1


def test_upsert_outage(con):
    o = Outage(
        zone=BiddingZone.FI, asset_name="Olkiluoto 2", fuel_type="nuclear",
        outage_type="planned", unavailable_mw=890.0,
        period_start=datetime(2024, 5, 1, tzinfo=UTC),
        period_end=datetime(2024, 5, 15, tzinfo=UTC),
        message_id="REMIT-001",
    )
    insert_outages(con, [o])
    o_updated = o.model_copy(update={"period_end": datetime(2024, 5, 20, tzinfo=UTC)})
    insert_outages(con, [o_updated])

    result = get_outages(con, BiddingZone.FI)
    assert len(result) == 1
    assert result[0].period_end == datetime(2024, 5, 20, tzinfo=UTC)


# ---- weather ----


def test_insert_and_query_weather(con):
    now = datetime(2024, 7, 1, 6, tzinfo=UTC)
    rows = [
        WeatherForecast(
            location_name="SE4_skane", latitude=56.0, longitude=14.0,
            period_start=datetime(2024, 7, 1, h, tzinfo=UTC),
            period_end=datetime(2024, 7, 1, h, tzinfo=UTC) + _1H,
            fetched_at=now,
            wind_speed_100m_ms=8.5, solar_irradiance_wm2=400.0, temperature_c=18.0,
        )
        for h in range(6, 18)
    ]
    insert_weather_forecasts(con, rows)

    result = get_weather_forecasts(
        con, "SE4_skane",
        datetime(2024, 7, 1, tzinfo=UTC), datetime(2024, 7, 2, tzinfo=UTC),
    )
    assert len(result) == 12
    assert result[0].wind_speed_100m_ms == 8.5


def test_weather_returns_latest_forecast(con):
    """When multiple forecast vintages exist, only the latest is returned."""
    ts = datetime(2024, 7, 1, 12, tzinfo=UTC)
    old_fc = WeatherForecast(
        location_name="FI_inland", latitude=61.5, longitude=24.0,
        period_start=ts, period_end=ts + _1H,
        fetched_at=datetime(2024, 6, 30, 6, tzinfo=UTC),
        wind_speed_100m_ms=5.0, solar_irradiance_wm2=None, temperature_c=15.0,
    )
    new_fc = WeatherForecast(
        location_name="FI_inland", latitude=61.5, longitude=24.0,
        period_start=ts, period_end=ts + _1H,
        fetched_at=datetime(2024, 7, 1, 6, tzinfo=UTC),
        wind_speed_100m_ms=7.2, solar_irradiance_wm2=None, temperature_c=16.0,
    )
    insert_weather_forecasts(con, [old_fc, new_fc])

    result = get_weather_forecasts(con, "FI_inland", datetime(2024, 7, 1, tzinfo=UTC), datetime(2024, 7, 2, tzinfo=UTC))
    assert len(result) == 1
    assert result[0].wind_speed_100m_ms == 7.2


# ---- empty inputs ----


def test_insert_empty_lists(con):
    assert insert_day_ahead_prices(con, []) == 0
    assert insert_generation_by_type(con, []) == 0
    assert insert_total_load(con, []) == 0
    assert insert_cross_border_flows(con, []) == 0
    assert insert_outages(con, []) == 0
    assert insert_weather_forecasts(con, []) == 0
