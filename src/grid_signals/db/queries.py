"""Thin data-access layer: insert and query helpers for every table."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import date, datetime

    import psycopg

from grid_signals.models import (
    BiddingZone,
    CrossBorderFlow,
    DayAheadPrice,
    GenerationByType,
    Outage,
    TotalLoad,
    WeatherForecast,
)

# Primary key columns per table — needed for ON CONFLICT upsert.
_PK_COLUMNS: dict[str, list[str]] = {
    "day_ahead_prices": ["zone", "period_start"],
    "generation_by_type": ["zone", "period_start", "fuel_type"],
    "total_load": ["zone", "period_start", "is_forecast"],
    "cross_border_flows": ["from_zone", "to_zone", "period_start"],
    "outages": ["message_id"],
    "weather_forecasts": ["location_name", "period_start", "fetched_at"],
}


def _bulk_upsert(
    con: psycopg.Connection,
    table: str,
    columns: list[str],
    data: list[tuple[Any, ...]],
) -> None:
    """Insert data with ON CONFLICT upsert for idempotent writes."""
    pk_cols = _PK_COLUMNS[table]
    cols = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    pk = ", ".join(pk_cols)
    update_cols = [c for c in columns if c not in pk_cols]
    if update_cols:
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        sql = (
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT ({pk}) DO UPDATE SET {updates}"
        )
    else:
        sql = (
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT ({pk}) DO NOTHING"
        )
    with con.cursor() as cur:
        cur.executemany(sql, data)


# ---------------------------------------------------------------------------
# Inserts (upsert via ON CONFLICT)
# ---------------------------------------------------------------------------


def insert_day_ahead_prices(con: psycopg.Connection, rows: list[DayAheadPrice]) -> int:
    if not rows:
        return 0
    _bulk_upsert(
        con,
        "day_ahead_prices",
        ["zone", "period_start", "period_end", "price_eur_mwh"],
        [(r.zone, r.period_start, r.period_end, r.price_eur_mwh) for r in rows],
    )
    return len(rows)


def insert_generation_by_type(
    con: psycopg.Connection, rows: list[GenerationByType]
) -> int:
    if not rows:
        return 0
    _bulk_upsert(
        con,
        "generation_by_type",
        ["zone", "period_start", "period_end", "fuel_type", "generation_mw"],
        [
            (r.zone, r.period_start, r.period_end, r.fuel_type, r.generation_mw)
            for r in rows
        ],
    )
    return len(rows)


def insert_total_load(con: psycopg.Connection, rows: list[TotalLoad]) -> int:
    if not rows:
        return 0
    _bulk_upsert(
        con,
        "total_load",
        ["zone", "period_start", "period_end", "load_mw", "is_forecast"],
        [
            (r.zone, r.period_start, r.period_end, r.load_mw, r.is_forecast)
            for r in rows
        ],
    )
    return len(rows)


def insert_cross_border_flows(
    con: psycopg.Connection, rows: list[CrossBorderFlow]
) -> int:
    if not rows:
        return 0
    _bulk_upsert(
        con,
        "cross_border_flows",
        ["from_zone", "to_zone", "period_start", "period_end", "flow_mw"],
        [
            (r.from_zone, r.to_zone, r.period_start, r.period_end, r.flow_mw)
            for r in rows
        ],
    )
    return len(rows)


def insert_outages(con: psycopg.Connection, rows: list[Outage]) -> int:
    if not rows:
        return 0
    _bulk_upsert(
        con,
        "outages",
        [
            "message_id",
            "zone",
            "asset_name",
            "fuel_type",
            "outage_type",
            "unavailable_mw",
            "period_start",
            "period_end",
        ],
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
    con: psycopg.Connection, rows: list[WeatherForecast]
) -> int:
    if not rows:
        return 0
    _bulk_upsert(
        con,
        "weather_forecasts",
        [
            "location_name",
            "latitude",
            "longitude",
            "period_start",
            "period_end",
            "fetched_at",
            "wind_speed_100m_ms",
            "solar_irradiance_wm2",
            "temperature_c",
        ],
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
    con: psycopg.Connection,
    zone: BiddingZone,
    start: datetime,
    end: datetime,
) -> list[DayAheadPrice]:
    rows = con.execute(
        """
        SELECT zone, period_start, period_end, price_eur_mwh
        FROM day_ahead_prices
        WHERE zone = %s AND period_start >= %s AND period_start < %s
        ORDER BY period_start
        """,
        [zone, start, end],
    ).fetchall()
    return [
        DayAheadPrice(zone=r[0], period_start=r[1], period_end=r[2], price_eur_mwh=r[3])
        for r in rows
    ]


def get_generation_mix(
    con: psycopg.Connection,
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
            WHERE zone = %s AND period_start >= %s AND period_start < %s AND fuel_type = %s
            ORDER BY period_start, fuel_type
            """,
            [zone, start, end, fuel_type],
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT zone, period_start, period_end, fuel_type, generation_mw
            FROM generation_by_type
            WHERE zone = %s AND period_start >= %s AND period_start < %s
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
    con: psycopg.Connection,
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
            WHERE zone = %s AND period_start >= %s AND period_start < %s AND is_forecast = true
            ORDER BY period_start
            """,
            [zone, start, end],
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT zone, period_start, period_end, load_mw, is_forecast
            FROM total_load
            WHERE zone = %s AND period_start >= %s AND period_start < %s
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
    con: psycopg.Connection,
    from_zone: str,
    to_zone: str,
    start: datetime,
    end: datetime,
) -> list[CrossBorderFlow]:
    rows = con.execute(
        """
        SELECT from_zone, to_zone, period_start, period_end, flow_mw
        FROM cross_border_flows
        WHERE from_zone = %s AND to_zone = %s AND period_start >= %s AND period_start < %s
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
    con: psycopg.Connection,
    zone: BiddingZone,
    fuel_type: str | None = None,
    active_at: datetime | None = None,
) -> list[Outage]:
    conditions = ["zone = %s"]
    params: list[object] = [zone]
    if fuel_type:
        conditions.append("fuel_type = %s")
        params.append(fuel_type)
    if active_at:
        conditions.extend(
            ["period_start <= %s", "(period_end IS NULL OR period_end >= %s)"]
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
    con: psycopg.Connection,
    location_name: str,
    start: datetime,
    end: datetime,
) -> list[WeatherForecast]:
    """Return the most recent forecast for each period in the range."""
    rows = con.execute(
        """
        SELECT location_name, latitude, longitude, period_start, period_end, fetched_at,
               wind_speed_100m_ms, solar_irradiance_wm2, temperature_c
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY location_name, period_start ORDER BY fetched_at DESC
                   ) AS rn
            FROM weather_forecasts
            WHERE location_name = %s AND period_start >= %s AND period_start < %s
        ) t
        WHERE rn = 1
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


# ---------------------------------------------------------------------------
# Briefings
# ---------------------------------------------------------------------------


def upsert_briefing(
    con: psycopg.Connection,
    briefing_date: date,
    content: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    tool_calls: int,
    cost_usd: float,
) -> None:
    """Insert or update a briefing for a given date."""
    con.execute(
        """
        INSERT INTO briefings (briefing_date, content, model, input_tokens, output_tokens,
                               tool_calls, cost_usd)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (briefing_date) DO UPDATE SET
            content = EXCLUDED.content,
            model = EXCLUDED.model,
            input_tokens = EXCLUDED.input_tokens,
            output_tokens = EXCLUDED.output_tokens,
            tool_calls = EXCLUDED.tool_calls,
            cost_usd = EXCLUDED.cost_usd,
            created_at = now()
        """,
        [
            briefing_date,
            content,
            model,
            input_tokens,
            output_tokens,
            tool_calls,
            cost_usd,
        ],
    )


def get_briefing(
    con: psycopg.Connection, briefing_date: date
) -> tuple[str, date] | None:
    """Return (content, created_at) for a single date, or None."""
    row = con.execute(
        "SELECT content, created_at FROM briefings WHERE briefing_date = %s",
        [briefing_date],
    ).fetchone()
    if row is None:
        return None
    return (row[0], row[1])


def list_briefing_dates(con: psycopg.Connection) -> list[date]:
    """Return all briefing dates, most recent first."""
    rows = con.execute(
        "SELECT briefing_date FROM briefings ORDER BY briefing_date DESC"
    ).fetchall()
    return [r[0] for r in rows]
