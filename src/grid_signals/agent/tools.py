"""Agent tool schemas (Anthropic API format) and dispatch logic."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime

import duckdb

from grid_signals.db.queries import (
    get_cross_border_flows,
    get_day_ahead_prices,
    get_generation_mix,
    get_outages,
    get_total_load,
    get_weather_forecasts,
)
from grid_signals.models import BiddingZone

# ---------------------------------------------------------------------------
# Tool schemas (Anthropic API format)
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "get_day_ahead_prices",
        "description": (
            "Get day-ahead electricity prices for a bidding zone. "
            "Returns daily statistics (mean, min, max with hours, peak/off-peak averages, "
            "compact hourly profile) instead of raw intervals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone": {
                    "type": "string",
                    "enum": [z.value for z in BiddingZone],
                    "description": "Bidding zone code",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD), inclusive",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD), exclusive",
                },
            },
            "required": ["zone", "start_date", "end_date"],
        },
    },
    {
        "name": "get_generation_mix",
        "description": (
            "Get daily generation totals and shares by fuel type for a bidding zone. "
            "Returns total_mwh, avg_mw, and share_pct per fuel type per day. "
            "Optionally filter by a specific fuel_type (e.g. wind_onshore, "
            "solar, nuclear, gas, oil_shale, hydro)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone": {
                    "type": "string",
                    "enum": [z.value for z in BiddingZone],
                    "description": "Bidding zone code",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD), inclusive",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD), exclusive",
                },
                "fuel_type": {
                    "type": "string",
                    "description": "Filter by fuel type (optional)",
                },
            },
            "required": ["zone", "start_date", "end_date"],
        },
    },
    {
        "name": "get_wind_forecast",
        "description": (
            "Get daily weather forecast summary (wind, solar, temperature "
            "mean/min/max) for a location. Use location names like SE4_skane, "
            "FI_inland, EE_tallinn, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Weather location name (e.g. SE4_skane, FI_inland)",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD), inclusive",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD), exclusive",
                },
            },
            "required": ["location", "start_date", "end_date"],
        },
    },
    {
        "name": "get_outages",
        "description": (
            "Get REMIT outage messages for a bidding zone. "
            "Optionally filter by fuel_type and/or a point-in-time "
            "(active_at) to find outages active at that moment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone": {
                    "type": "string",
                    "enum": [z.value for z in BiddingZone],
                    "description": "Bidding zone code",
                },
                "fuel_type": {
                    "type": "string",
                    "description": "Filter by fuel type (optional)",
                },
                "active_at": {
                    "type": "string",
                    "description": (
                        "ISO datetime or YYYY-MM-DD to find outages active "
                        "at that time (optional)"
                    ),
                },
            },
            "required": ["zone"],
        },
    },
    {
        "name": "get_cross_border_flows",
        "description": (
            "Get daily cross-border flow summary (mean, min, max, direction changes) "
            "between two zones. Positive flow_mw means power flows from from_zone to to_zone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "from_zone": {
                    "type": "string",
                    "enum": [z.value for z in BiddingZone],
                    "description": "Exporting zone",
                },
                "to_zone": {
                    "type": "string",
                    "enum": [z.value for z in BiddingZone],
                    "description": "Importing zone",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD), inclusive",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD), exclusive",
                },
            },
            "required": ["from_zone", "to_zone", "start_date", "end_date"],
        },
    },
    {
        "name": "get_load_forecast",
        "description": (
            "Get daily load forecast summary (mean, min with hour, max with hour) "
            "for a bidding zone. Returns only forecast values (not actuals)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone": {
                    "type": "string",
                    "enum": [z.value for z in BiddingZone],
                    "description": "Bidding zone code",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD), inclusive",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD), exclusive",
                },
            },
            "required": ["zone", "start_date", "end_date"],
        },
    },
    {
        "name": "calculate_spread",
        "description": (
            "Calculate price spread between two bidding zones "
            "(zone_1 price minus zone_2 price). Returns summary statistics "
            "(mean, min, max, hours with positive/negative spread)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_1": {
                    "type": "string",
                    "enum": [z.value for z in BiddingZone],
                    "description": "First zone (spread = zone_1 - zone_2)",
                },
                "zone_2": {
                    "type": "string",
                    "enum": [z.value for z in BiddingZone],
                    "description": "Second zone",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD), inclusive",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD), exclusive",
                },
            },
            "required": ["zone_1", "zone_2", "start_date", "end_date"],
        },
    },
    {
        "name": "get_historical_similar_days",
        "description": (
            "Find past days with similar weather conditions (average wind "
            "speed and temperature) at a given location, and return their "
            "price summaries for a zone. Useful for estimating what prices "
            "might look like given a weather forecast."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone": {
                    "type": "string",
                    "enum": [z.value for z in BiddingZone],
                    "description": "Bidding zone for price data",
                },
                "location": {
                    "type": "string",
                    "description": "Weather location name (e.g. EE_tallinn)",
                },
                "target_wind_ms": {
                    "type": "number",
                    "description": "Target average wind speed in m/s",
                },
                "target_temp_c": {
                    "type": "number",
                    "description": "Target average temperature in °C",
                },
                "wind_tolerance_ms": {
                    "type": "number",
                    "description": "Wind speed tolerance band in m/s (default 2.0)",
                },
                "temp_tolerance_c": {
                    "type": "number",
                    "description": "Temperature tolerance band in °C (default 3.0)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of similar days to return (default 10)",
                },
            },
            "required": ["zone", "location", "target_wind_ms", "target_temp_c"],
        },
    },
]

# ---------------------------------------------------------------------------
# Date parsing helper
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> datetime:
    """Parse a YYYY-MM-DD string to a UTC datetime."""
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _parse_datetime(s: str) -> datetime:
    """Parse YYYY-MM-DD or ISO datetime string to UTC datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s!r}")


# ---------------------------------------------------------------------------
# Summary helpers — compact daily aggregates for token efficiency
# ---------------------------------------------------------------------------


def _summarize_prices(rows: list) -> list[dict]:
    """Group price rows by date; return daily stats."""
    by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        day = r.period_start.strftime("%Y-%m-%d")
        by_date[day].append(r)
    result = []
    for day, prices in sorted(by_date.items()):
        vals = [p.price_eur_mwh for p in prices]
        hours = [p.period_start.hour for p in prices]
        min_idx = vals.index(min(vals))
        max_idx = vals.index(max(vals))
        peak = [v for v, h in zip(vals, hours) if 8 <= h < 20]
        offpeak = [v for v, h in zip(vals, hours) if h < 8 or h >= 20]
        result.append({
            "date": day,
            "zone": prices[0].zone.value,
            "count": len(vals),
            "mean": round(sum(vals) / len(vals), 2),
            "min": round(min(vals), 2),
            "min_hour": hours[min_idx],
            "max": round(max(vals), 2),
            "max_hour": hours[max_idx],
            "peak_avg": round(sum(peak) / len(peak), 2) if peak else None,
            "offpeak_avg": round(sum(offpeak) / len(offpeak), 2) if offpeak else None,
            "hourly": [round(v, 2) for v in vals],
        })
    return result


def _summarize_generation(rows: list) -> list[dict]:
    """Group generation rows by date; return fuel-type totals and shares."""
    by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        day = r.period_start.strftime("%Y-%m-%d")
        by_date[day].append(r)
    result = []
    for day, entries in sorted(by_date.items()):
        # Determine interval hours from period_start/period_end
        fuel_totals: dict[str, float] = defaultdict(float)
        fuel_counts: dict[str, int] = defaultdict(int)
        for e in entries:
            hours = (e.period_end - e.period_start).total_seconds() / 3600
            fuel_totals[e.fuel_type] += e.generation_mw * hours
            fuel_counts[e.fuel_type] += 1
        total_mwh = sum(fuel_totals.values())
        fuels = []
        for ft in sorted(fuel_totals.keys()):
            mwh = fuel_totals[ft]
            fuels.append({
                "fuel_type": ft,
                "total_mwh": round(mwh, 1),
                "avg_mw": round(mwh / (fuel_counts[ft] * ((entries[0].period_end - entries[0].period_start).total_seconds() / 3600)) if fuel_counts[ft] else 0, 1),
                "share_pct": round(mwh / total_mwh * 100, 1) if total_mwh else 0,
            })
        result.append({
            "date": day,
            "zone": entries[0].zone.value,
            "total_mwh": round(total_mwh, 1),
            "fuels": fuels,
        })
    return result


def _summarize_weather(rows: list) -> list[dict]:
    """Group weather rows by date; return daily summary stats."""
    by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        day = r.period_start.strftime("%Y-%m-%d")
        by_date[day].append(r)
    result = []
    for day, entries in sorted(by_date.items()):
        winds = [e.wind_speed_100m_ms for e in entries if e.wind_speed_100m_ms is not None]
        temps = [e.temperature_c for e in entries if e.temperature_c is not None]
        solars = [e.solar_irradiance_wm2 for e in entries if e.solar_irradiance_wm2 is not None]
        summary: dict = {"date": day, "location": entries[0].location_name, "count": len(entries)}
        if winds:
            summary["wind"] = {"mean": round(sum(winds) / len(winds), 1), "min": round(min(winds), 1), "max": round(max(winds), 1)}
        if temps:
            summary["temperature"] = {"mean": round(sum(temps) / len(temps), 1), "min": round(min(temps), 1), "max": round(max(temps), 1)}
        if solars:
            summary["solar"] = {"mean": round(sum(solars) / len(solars), 1), "max": round(max(solars), 1)}
        result.append(summary)
    return result


def _summarize_flows(rows: list) -> list[dict]:
    """Group flow rows by date; return daily summary stats."""
    by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        day = r.period_start.strftime("%Y-%m-%d")
        by_date[day].append(r)
    result = []
    for day, entries in sorted(by_date.items()):
        vals = [e.flow_mw for e in entries]
        direction_changes = sum(
            1 for i in range(1, len(vals))
            if (vals[i] >= 0) != (vals[i - 1] >= 0)
        )
        result.append({
            "date": day,
            "from_zone": entries[0].from_zone.value,
            "to_zone": entries[0].to_zone.value,
            "count": len(vals),
            "mean_flow_mw": round(sum(vals) / len(vals), 1),
            "min_flow_mw": round(min(vals), 1),
            "max_flow_mw": round(max(vals), 1),
            "direction_changes": direction_changes,
        })
    return result


def _summarize_load(rows: list) -> list[dict]:
    """Group load rows by date; return daily summary stats."""
    by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        day = r.period_start.strftime("%Y-%m-%d")
        by_date[day].append(r)
    result = []
    for day, entries in sorted(by_date.items()):
        vals = [e.load_mw for e in entries]
        hours = [e.period_start.hour for e in entries]
        min_idx = vals.index(min(vals))
        max_idx = vals.index(max(vals))
        result.append({
            "date": day,
            "zone": entries[0].zone.value,
            "count": len(vals),
            "mean_mw": round(sum(vals) / len(vals), 1),
            "min_mw": round(min(vals), 1),
            "min_hour": hours[min_idx],
            "max_mw": round(max(vals), 1),
            "max_hour": hours[max_idx],
        })
    return result


# ---------------------------------------------------------------------------
# Computed tools
# ---------------------------------------------------------------------------


def _calculate_spread(
    con: duckdb.DuckDBPyConnection,
    zone_1: str,
    zone_2: str,
    start: datetime,
    end: datetime,
) -> dict:
    prices_1 = get_day_ahead_prices(con, BiddingZone(zone_1), start, end)
    prices_2 = get_day_ahead_prices(con, BiddingZone(zone_2), start, end)

    lookup_2 = {p.period_start: p.price_eur_mwh for p in prices_2}

    hourly: list[dict] = []
    for p in prices_1:
        if p.period_start in lookup_2:
            spread = round(p.price_eur_mwh - lookup_2[p.period_start], 2)
            hourly.append({
                "period_start": p.period_start.isoformat(),
                "zone_1_price": p.price_eur_mwh,
                "zone_2_price": lookup_2[p.period_start],
                "spread": spread,
            })

    if not hourly:
        return {
            "zone_1": zone_1,
            "zone_2": zone_2,
            "summary": None,
        }

    spreads = [h["spread"] for h in hourly]
    return {
        "zone_1": zone_1,
        "zone_2": zone_2,
        "summary": {
            "mean_spread": round(sum(spreads) / len(spreads), 2),
            "min_spread": min(spreads),
            "max_spread": max(spreads),
            "hours_positive": sum(1 for s in spreads if s > 0),
            "hours_negative": sum(1 for s in spreads if s < 0),
            "hours_zero": sum(1 for s in spreads if s == 0),
            "total_hours": len(spreads),
        },
    }


def _get_historical_similar_days(
    con: duckdb.DuckDBPyConnection,
    zone: str,
    location: str,
    target_wind_ms: float,
    target_temp_c: float,
    wind_tolerance_ms: float = 2.0,
    temp_tolerance_c: float = 3.0,
    limit: int = 10,
) -> dict:
    rows = con.execute(
        """
        WITH daily_weather AS (
            SELECT
                date_trunc('day', period_start) AS day,
                avg(wind_speed_100m_ms) AS avg_wind,
                avg(temperature_c) AS avg_temp
            FROM weather_forecasts
            WHERE location_name = ?
              AND wind_speed_100m_ms IS NOT NULL
              AND temperature_c IS NOT NULL
            GROUP BY date_trunc('day', period_start)
        ),
        similar_days AS (
            SELECT day, avg_wind, avg_temp
            FROM daily_weather
            WHERE abs(avg_wind - ?) <= ?
              AND abs(avg_temp - ?) <= ?
        ),
        daily_prices AS (
            SELECT
                date_trunc('day', period_start) AS day,
                avg(price_eur_mwh) AS avg_price,
                min(price_eur_mwh) AS min_price,
                max(price_eur_mwh) AS max_price
            FROM day_ahead_prices
            WHERE zone = ?
            GROUP BY date_trunc('day', period_start)
        )
        SELECT
            s.day, s.avg_wind, s.avg_temp,
            p.avg_price, p.min_price, p.max_price
        FROM similar_days s
        JOIN daily_prices p ON s.day = p.day
        ORDER BY s.day DESC
        LIMIT ?
        """,
        [
            location,
            target_wind_ms, wind_tolerance_ms,
            target_temp_c, temp_tolerance_c,
            zone,
            limit,
        ],
    ).fetchall()

    days = [
        {
            "date": r[0].strftime("%Y-%m-%d") if hasattr(r[0], "strftime") else str(r[0]),
            "avg_wind_ms": round(r[1], 1),
            "avg_temp_c": round(r[2], 1),
            "avg_price_eur_mwh": round(r[3], 2),
            "min_price_eur_mwh": round(r[4], 2),
            "max_price_eur_mwh": round(r[5], 2),
        }
        for r in rows
    ]

    return {
        "zone": zone,
        "location": location,
        "target_wind_ms": target_wind_ms,
        "target_temp_c": target_temp_c,
        "matching_days": len(days),
        "days": days,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def execute_tool(
    name: str,
    tool_input: dict,
    con: duckdb.DuckDBPyConnection,
) -> str:
    """Execute an agent tool call and return a JSON string result.

    Errors are caught and returned as ``{"error": "..."}`` — no exceptions
    leak to the conversation loop.
    """
    try:
        result = _dispatch(name, tool_input, con)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def _dispatch(
    name: str,
    tool_input: dict,
    con: duckdb.DuckDBPyConnection,
) -> object:
    if name == "get_day_ahead_prices":
        rows = get_day_ahead_prices(
            con,
            BiddingZone(tool_input["zone"]),
            _parse_date(tool_input["start_date"]),
            _parse_date(tool_input["end_date"]),
        )
        return _summarize_prices(rows)

    if name == "get_generation_mix":
        rows = get_generation_mix(
            con,
            BiddingZone(tool_input["zone"]),
            _parse_date(tool_input["start_date"]),
            _parse_date(tool_input["end_date"]),
            fuel_type=tool_input.get("fuel_type"),
        )
        return _summarize_generation(rows)

    if name == "get_wind_forecast":
        rows = get_weather_forecasts(
            con,
            tool_input["location"],
            _parse_date(tool_input["start_date"]),
            _parse_date(tool_input["end_date"]),
        )
        return _summarize_weather(rows)

    if name == "get_outages":
        active_at = None
        if "active_at" in tool_input and tool_input["active_at"]:
            active_at = _parse_datetime(tool_input["active_at"])
        rows = get_outages(
            con,
            BiddingZone(tool_input["zone"]),
            fuel_type=tool_input.get("fuel_type"),
            active_at=active_at,
        )
        return [r.model_dump(mode="json") for r in rows]

    if name == "get_cross_border_flows":
        rows = get_cross_border_flows(
            con,
            BiddingZone(tool_input["from_zone"]),
            BiddingZone(tool_input["to_zone"]),
            _parse_date(tool_input["start_date"]),
            _parse_date(tool_input["end_date"]),
        )
        return _summarize_flows(rows)

    if name == "get_load_forecast":
        rows = get_total_load(
            con,
            BiddingZone(tool_input["zone"]),
            _parse_date(tool_input["start_date"]),
            _parse_date(tool_input["end_date"]),
            forecast_only=True,
        )
        return _summarize_load(rows)

    if name == "calculate_spread":
        return _calculate_spread(
            con,
            tool_input["zone_1"],
            tool_input["zone_2"],
            _parse_date(tool_input["start_date"]),
            _parse_date(tool_input["end_date"]),
        )

    if name == "get_historical_similar_days":
        return _get_historical_similar_days(
            con,
            tool_input["zone"],
            tool_input["location"],
            tool_input["target_wind_ms"],
            tool_input["target_temp_c"],
            wind_tolerance_ms=tool_input.get("wind_tolerance_ms", 2.0),
            temp_tolerance_c=tool_input.get("temp_tolerance_c", 3.0),
            limit=tool_input.get("limit", 10),
        )

    raise ValueError(f"Unknown tool: {name!r}")
