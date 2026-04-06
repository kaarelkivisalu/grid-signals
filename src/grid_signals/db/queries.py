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
        INSERT OR REPLACE INTO day_ahead_prices (zone, period_start, period_end, price_eur_mwh)
        VALUES (?, ?, ?, ?)
        """,
        [(r.zone, r.period_start, r.period_end, r.price_eur_mwh) for r in rows],
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
            (zone, period_start, period_end, fuel_type, generation_mw)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (r.zone, r.period_start, r.period_end, r.fuel_type, r.generation_mw)
            for r in rows
        ],
    )
    return len(rows)


def insert_total_load(con: duckdb.DuckDBPyConnection, rows: list[TotalLoad]) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO total_load (zone, period_start, period_end, load_mw, is_forecast)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (r.zone, r.period_start, r.period_end, r.load_mw, r.is_forecast)
            for r in rows
        ],
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
            (from_zone, to_zone, period_start, period_end, flow_mw)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (r.from_zone, r.to_zone, r.period_start, r.period_end, r.flow_mw)
            for r in rows
        ],
    )
    return len(rows)


def insert_outages(con: duckdb.DuckDBPyConnection, rows: list[Outage]) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO outages
            (message_id, zone, asset_name, fuel_type, outage_type,
             unavailable_mw, period_start, period_end)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r.message_id,
                r.zone,
                r.asset_name,
                r.fuel_type,
                r.outage_type,
                r.unavailable_mw,
                r.period_start,
                r.period_end,
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
            (location_name, latitude, longitude, period_start, period_end, fetched_at,
             wind_speed_100m_ms, solar_irradiance_wm2, temperature_c)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r.location_name,
                r.latitude,
                r.longitude,
                r.period_start,
                r.period_end,
                r.fetched_at,
                r.wind_speed_100m_ms,
                r.solar_irradiance_wm2,
                r.temperature_c,
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
        SELECT zone, period_start, period_end, price_eur_mwh
        FROM day_ahead_prices
        WHERE zone = ? AND period_start >= ? AND period_start < ?
        ORDER BY period_start
        """,
        [zone, start, end],
    ).fetchall()
    return [
        DayAheadPrice(zone=r[0], period_start=r[1], period_end=r[2], price_eur_mwh=r[3])
        for r in rows
    ]


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
            SELECT zone, period_start, period_end, fuel_type, generation_mw
            FROM generation_by_type
            WHERE zone = ? AND period_start >= ? AND period_start < ? AND fuel_type = ?
            ORDER BY period_start, fuel_type
            """,
            [zone, start, end, fuel_type],
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT zone, period_start, period_end, fuel_type, generation_mw
            FROM generation_by_type
            WHERE zone = ? AND period_start >= ? AND period_start < ?
            ORDER BY period_start, fuel_type
            """,
            [zone, start, end],
        ).fetchall()
    return [
        GenerationByType(
            zone=r[0],
            period_start=r[1],
            period_end=r[2],
            fuel_type=r[3],
            generation_mw=r[4],
        )
        for r in rows
    ]


def get_total_load(
    con: duckdb.DuckDBPyConnection,
    zone: BiddingZone,
    start: datetime,
    end: datetime,
    *,
    forecast_only: bool = False,
) -> list[TotalLoad]:
    if forecast_only:
        rows = con.execute(
            """
            SELECT zone, period_start, period_end, load_mw, is_forecast
            FROM total_load
            WHERE zone = ? AND period_start >= ? AND period_start < ? AND is_forecast = true
            ORDER BY period_start
            """,
            [zone, start, end],
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT zone, period_start, period_end, load_mw, is_forecast
            FROM total_load
            WHERE zone = ? AND period_start >= ? AND period_start < ?
            ORDER BY period_start
            """,
            [zone, start, end],
        ).fetchall()
    return [
        TotalLoad(
            zone=r[0],
            period_start=r[1],
            period_end=r[2],
            load_mw=r[3],
            is_forecast=r[4],
        )
        for r in rows
    ]


def get_cross_border_flows(
    con: duckdb.DuckDBPyConnection,
    from_zone: str,
    to_zone: str,
    start: datetime,
    end: datetime,
) -> list[CrossBorderFlow]:
    rows = con.execute(
        """
        SELECT from_zone, to_zone, period_start, period_end, flow_mw
        FROM cross_border_flows
        WHERE from_zone = ? AND to_zone = ? AND period_start >= ? AND period_start < ?
        ORDER BY period_start
        """,
        [from_zone, to_zone, start, end],
    ).fetchall()
    return [
        CrossBorderFlow(
            from_zone=r[0],
            to_zone=r[1],
            period_start=r[2],
            period_end=r[3],
            flow_mw=r[4],
        )
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
        conditions.extend(
            ["period_start <= ?", "(period_end IS NULL OR period_end >= ?)"]
        )
        params.extend((active_at, active_at))
    where = " AND ".join(conditions)
    rows = con.execute(
        f"""
        SELECT message_id, zone, asset_name, fuel_type, outage_type,
               unavailable_mw, period_start, period_end
        FROM outages
        WHERE {where}
        ORDER BY period_start
        """,
        params,
    ).fetchall()
    return [
        Outage(
            message_id=r[0],
            zone=r[1],
            asset_name=r[2],
            fuel_type=r[3],
            outage_type=r[4],
            unavailable_mw=r[5],
            period_start=r[6],
            period_end=r[7],
        )
        for r in rows
    ]


def get_weather_forecasts(
    con: duckdb.DuckDBPyConnection,
    location_name: str,
    start: datetime,
    end: datetime,
) -> list[WeatherForecast]:
    """Return the most recent forecast for each period in the range."""
    rows = con.execute(
        """
        SELECT location_name, latitude, longitude, period_start, period_end, fetched_at,
               wind_speed_100m_ms, solar_irradiance_wm2, temperature_c
        FROM weather_forecasts
        WHERE location_name = ? AND period_start >= ? AND period_start < ?
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY location_name, period_start ORDER BY fetched_at DESC
        ) = 1
        ORDER BY period_start
        """,
        [location_name, start, end],
    ).fetchall()
    return [
        WeatherForecast(
            location_name=r[0],
            latitude=r[1],
            longitude=r[2],
            period_start=r[3],
            period_end=r[4],
            fetched_at=r[5],
            wind_speed_100m_ms=r[6],
            solar_irradiance_wm2=r[7],
            temperature_c=r[8],
        )
        for r in rows
    ]
