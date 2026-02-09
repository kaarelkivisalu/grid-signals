"""Thin data-access layer: insert and query helpers for every table."""

from datetime import datetime

import duckdb

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
# Inserts (upsert via INSERT OR REPLACE)
# ---------------------------------------------------------------------------


def insert_day_ahead_prices(
    con: duckdb.DuckDBPyConnection, rows: list[DayAheadPrice]
) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO day_ahead_prices (zone, timestamp, price_eur_mwh)
        VALUES (?, ?, ?)
        """,
        [(r.zone, r.timestamp, r.price_eur_mwh) for r in rows],
    )
    return len(rows)


def insert_generation_by_type(
    con: duckdb.DuckDBPyConnection, rows: list[GenerationByType]
) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO generation_by_type
            (zone, timestamp, fuel_type, generation_mw)
        VALUES (?, ?, ?, ?)
        """,
        [(r.zone, r.timestamp, r.fuel_type, r.generation_mw) for r in rows],
    )
    return len(rows)


def insert_total_load(
    con: duckdb.DuckDBPyConnection, rows: list[TotalLoad]
) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO total_load (zone, timestamp, load_mw, is_forecast)
        VALUES (?, ?, ?, ?)
        """,
        [(r.zone, r.timestamp, r.load_mw, r.is_forecast) for r in rows],
    )
    return len(rows)


def insert_cross_border_flows(
    con: duckdb.DuckDBPyConnection, rows: list[CrossBorderFlow]
) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO cross_border_flows
            (from_zone, to_zone, timestamp, flow_mw)
        VALUES (?, ?, ?, ?)
        """,
        [(r.from_zone, r.to_zone, r.timestamp, r.flow_mw) for r in rows],
    )
    return len(rows)


def insert_outages(
    con: duckdb.DuckDBPyConnection, rows: list[Outage]
) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO outages
            (message_id, zone, asset_name, fuel_type, outage_type,
             unavailable_mw, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r.message_id, r.zone, r.asset_name, r.fuel_type,
                r.outage_type, r.unavailable_mw, r.start_time, r.end_time,
            )
            for r in rows
        ],
    )
    return len(rows)


def insert_weather_forecasts(
    con: duckdb.DuckDBPyConnection, rows: list[WeatherForecast]
) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO weather_forecasts
            (location_name, latitude, longitude, timestamp, fetched_at,
             wind_speed_100m_ms, solar_irradiance_wm2, temperature_c)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r.location_name, r.latitude, r.longitude, r.timestamp,
                r.fetched_at, r.wind_speed_100m_ms,
                r.solar_irradiance_wm2, r.temperature_c,
            )
            for r in rows
        ],
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def get_day_ahead_prices(
    con: duckdb.DuckDBPyConnection,
    zone: BiddingZone,
    start: datetime,
    end: datetime,
) -> list[DayAheadPrice]:
    rows = con.execute(
        """
        SELECT zone, timestamp, price_eur_mwh
        FROM day_ahead_prices
        WHERE zone = ? AND timestamp >= ? AND timestamp < ?
        ORDER BY timestamp
        """,
        [zone, start, end],
    ).fetchall()
    return [DayAheadPrice(zone=r[0], timestamp=r[1], price_eur_mwh=r[2]) for r in rows]


def get_generation_mix(
    con: duckdb.DuckDBPyConnection,
    zone: BiddingZone,
    start: datetime,
    end: datetime,
    fuel_type: str | None = None,
) -> list[GenerationByType]:
    if fuel_type:
        rows = con.execute(
            """
            SELECT zone, timestamp, fuel_type, generation_mw
            FROM generation_by_type
            WHERE zone = ? AND timestamp >= ? AND timestamp < ? AND fuel_type = ?
            ORDER BY timestamp, fuel_type
            """,
            [zone, start, end, fuel_type],
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT zone, timestamp, fuel_type, generation_mw
            FROM generation_by_type
            WHERE zone = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp, fuel_type
            """,
            [zone, start, end],
        ).fetchall()
    return [
        GenerationByType(zone=r[0], timestamp=r[1], fuel_type=r[2], generation_mw=r[3])
        for r in rows
    ]


def get_total_load(
    con: duckdb.DuckDBPyConnection,
    zone: BiddingZone,
    start: datetime,
    end: datetime,
    forecast_only: bool = False,
) -> list[TotalLoad]:
    if forecast_only:
        rows = con.execute(
            """
            SELECT zone, timestamp, load_mw, is_forecast
            FROM total_load
            WHERE zone = ? AND timestamp >= ? AND timestamp < ? AND is_forecast = true
            ORDER BY timestamp
            """,
            [zone, start, end],
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT zone, timestamp, load_mw, is_forecast
            FROM total_load
            WHERE zone = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp
            """,
            [zone, start, end],
        ).fetchall()
    return [
        TotalLoad(zone=r[0], timestamp=r[1], load_mw=r[2], is_forecast=r[3])
        for r in rows
    ]


def get_cross_border_flows(
    con: duckdb.DuckDBPyConnection,
    from_zone: BiddingZone,
    to_zone: BiddingZone,
    start: datetime,
    end: datetime,
) -> list[CrossBorderFlow]:
    rows = con.execute(
        """
        SELECT from_zone, to_zone, timestamp, flow_mw
        FROM cross_border_flows
        WHERE from_zone = ? AND to_zone = ? AND timestamp >= ? AND timestamp < ?
        ORDER BY timestamp
        """,
        [from_zone, to_zone, start, end],
    ).fetchall()
    return [
        CrossBorderFlow(from_zone=r[0], to_zone=r[1], timestamp=r[2], flow_mw=r[3])
        for r in rows
    ]


def get_outages(
    con: duckdb.DuckDBPyConnection,
    zone: BiddingZone,
    fuel_type: str | None = None,
    active_at: datetime | None = None,
) -> list[Outage]:
    conditions = ["zone = ?"]
    params: list[object] = [zone]
    if fuel_type:
        conditions.append("fuel_type = ?")
        params.append(fuel_type)
    if active_at:
        conditions.append("start_time <= ?")
        params.append(active_at)
        conditions.append("(end_time IS NULL OR end_time >= ?)")
        params.append(active_at)
    where = " AND ".join(conditions)
    rows = con.execute(
        f"""
        SELECT message_id, zone, asset_name, fuel_type, outage_type,
               unavailable_mw, start_time, end_time
        FROM outages
        WHERE {where}
        ORDER BY start_time
        """,
        params,
    ).fetchall()
    return [
        Outage(
            message_id=r[0], zone=r[1], asset_name=r[2], fuel_type=r[3],
            outage_type=r[4], unavailable_mw=r[5], start_time=r[6], end_time=r[7],
        )
        for r in rows
    ]


def get_weather_forecasts(
    con: duckdb.DuckDBPyConnection,
    location_name: str,
    start: datetime,
    end: datetime,
) -> list[WeatherForecast]:
    """Return the most recent forecast for each hour in the range."""
    rows = con.execute(
        """
        SELECT location_name, latitude, longitude, timestamp, fetched_at,
               wind_speed_100m_ms, solar_irradiance_wm2, temperature_c
        FROM weather_forecasts
        WHERE location_name = ? AND timestamp >= ? AND timestamp < ?
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY location_name, timestamp ORDER BY fetched_at DESC
        ) = 1
        ORDER BY timestamp
        """,
        [location_name, start, end],
    ).fetchall()
    return [
        WeatherForecast(
            location_name=r[0], latitude=r[1], longitude=r[2], timestamp=r[3],
            fetched_at=r[4], wind_speed_100m_ms=r[5],
            solar_irradiance_wm2=r[6], temperature_c=r[7],
        )
        for r in rows
    ]
