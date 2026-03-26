"""Plotly figure builders for the dashboard."""

from __future__ import annotations

import duckdb
import plotly.graph_objects as go


def hourly_prices(con: duckdb.DuckDBPyConnection, zones: list[str],
                  start: str, end: str) -> go.Figure:
    """Line chart of hourly prices, one line per zone."""
    fig = go.Figure()
    for zone in zones:
        rows = con.execute(
            """
            SELECT period_start, price_eur_mwh
            FROM day_ahead_prices
            WHERE zone = ? AND period_start >= ? AND period_start < ?
            ORDER BY period_start
            """,
            [zone, start, end],
        ).fetchall()
        if rows:
            times = [r[0] for r in rows]
            prices = [r[1] for r in rows]
            fig.add_trace(go.Scatter(x=times, y=prices, name=zone, mode="lines"))
    fig.update_layout(
        title="Day-Ahead Prices",
        xaxis_title="Time (UTC)",
        yaxis_title="EUR/MWh",
        legend_title="Zone",
        hovermode="x unified",
    )
    return fig


def generation_mix(con: duckdb.DuckDBPyConnection, zone: str,
                   start: str, end: str) -> go.Figure:
    """Stacked bar chart of generation by fuel type."""
    rows = con.execute(
        """
        SELECT fuel_type,
               date_trunc('day', period_start) AS day,
               sum(generation_mw * (epoch(period_end) - epoch(period_start)) / 3600) AS total_mwh
        FROM generation_by_type
        WHERE zone = ? AND period_start >= ? AND period_start < ?
        GROUP BY fuel_type, day
        ORDER BY day, fuel_type
        """,
        [zone, start, end],
    ).fetchall()
    if not rows:
        fig = go.Figure()
        fig.update_layout(title=f"Generation Mix — {zone}", annotations=[
            dict(text="No data", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        ])
        return fig

    fuels: dict[str, dict] = {}
    days_set: list = []
    for fuel, day, mwh in rows:
        if day not in days_set:
            days_set.append(day)
        fuels.setdefault(fuel, {})[day] = mwh

    fig = go.Figure()
    for fuel in sorted(fuels.keys()):
        vals = [fuels[fuel].get(d, 0) for d in days_set]
        fig.add_trace(go.Bar(x=days_set, y=vals, name=fuel))
    fig.update_layout(
        barmode="stack",
        title=f"Generation Mix — {zone}",
        xaxis_title="Date",
        yaxis_title="MWh",
        legend_title="Fuel Type",
    )
    return fig


def cross_border_flows(con: duckdb.DuckDBPyConnection, from_zone: str,
                       to_zone: str, start: str, end: str) -> go.Figure:
    """Line chart of cross-border flows in MW."""
    rows = con.execute(
        """
        SELECT period_start, flow_mw
        FROM cross_border_flows
        WHERE from_zone = ? AND to_zone = ? AND period_start >= ? AND period_start < ?
        ORDER BY period_start
        """,
        [from_zone, to_zone, start, end],
    ).fetchall()
    fig = go.Figure()
    if rows:
        times = [r[0] for r in rows]
        flows = [r[1] for r in rows]
        fig.add_trace(go.Scatter(x=times, y=flows, mode="lines",
                                 name=f"{from_zone} → {to_zone}"))
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        title=f"Cross-Border Flows: {from_zone} → {to_zone}",
        xaxis_title="Time (UTC)",
        yaxis_title="MW (positive = export)",
        hovermode="x unified",
    )
    return fig


def wind_vs_price(con: duckdb.DuckDBPyConnection, zone: str, location: str,
                  start: str, end: str) -> go.Figure:
    """Dual-axis chart: wind speed and price."""
    prices = con.execute(
        """
        SELECT period_start, price_eur_mwh
        FROM day_ahead_prices
        WHERE zone = ? AND period_start >= ? AND period_start < ?
        ORDER BY period_start
        """,
        [zone, start, end],
    ).fetchall()
    weather = con.execute(
        """
        SELECT period_start, wind_speed_100m_ms
        FROM weather_forecasts
        WHERE location_name = ? AND period_start >= ? AND period_start < ?
          AND wind_speed_100m_ms IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY period_start ORDER BY fetched_at DESC
        ) = 1
        ORDER BY period_start
        """,
        [location, start, end],
    ).fetchall()

    from plotly.subplots import make_subplots
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if weather:
        fig.add_trace(
            go.Scatter(x=[r[0] for r in weather], y=[r[1] for r in weather],
                       name="Wind (m/s)", mode="lines", line=dict(color="#26A69A")),
            secondary_y=False,
        )
    if prices:
        fig.add_trace(
            go.Scatter(x=[r[0] for r in prices], y=[r[1] for r in prices],
                       name="Price (EUR/MWh)", mode="lines", line=dict(color="#EF5350")),
            secondary_y=True,
        )
    fig.update_layout(
        title=f"Wind vs Price — {zone} / {location}",
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Wind Speed (m/s)", secondary_y=False)
    fig.update_yaxes(title_text="EUR/MWh", secondary_y=True)
    return fig


def price_heatmap(con: duckdb.DuckDBPyConnection, zones: list[str],
                  date: str) -> go.Figure:
    """Heatmap: zones x hours, color = price for a single day."""
    rows = con.execute(
        """
        SELECT zone, extract(hour FROM period_start) AS hour, price_eur_mwh
        FROM day_ahead_prices
        WHERE zone = ANY(?) AND period_start >= ?::DATE AND period_start < ?::DATE + INTERVAL 1 DAY
        ORDER BY zone, hour
        """,
        [zones, date, date],
    ).fetchall()

    if not rows:
        fig = go.Figure()
        fig.update_layout(title="Price Heatmap", annotations=[
            dict(text="No data", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        ])
        return fig

    zone_data: dict[str, dict[int, float]] = {}
    for zone, hour, price in rows:
        zone_data.setdefault(zone, {})[int(hour)] = price

    zone_labels = sorted(zone_data.keys())
    hours = list(range(24))
    z = [[zone_data.get(z, {}).get(h, None) for h in hours] for z in zone_labels]

    fig = go.Figure(go.Heatmap(
        z=z, x=[f"{h:02d}:00" for h in hours], y=zone_labels,
        colorscale="RdYlGn_r", colorbar_title="EUR/MWh",
    ))
    fig.update_layout(
        title=f"Price Heatmap — {date}",
        xaxis_title="Hour (UTC)",
        yaxis_title="Zone",
    )
    return fig
