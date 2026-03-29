"""Plotly figure builders for the dashboard."""

from __future__ import annotations

import math

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


# --- Interconnector flow map ---

# Approximate geographic centers per bidding zone.
_ZONE_COORDS: dict[str, tuple[float, float]] = {
    "EE": (59.0, 25.0),
    "LV": (57.0, 24.0),
    "LT": (55.5, 24.0),
    "FI": (62.0, 24.0),
    "SE1": (65.6, 22.1),
    "SE2": (62.4, 17.3),
    "SE3": (59.0, 16.0),
    "SE4": (56.0, 14.0),
    "NO1": (59.9, 10.7),
    "NO2": (58.1, 8.0),
    "NO3": (63.4, 10.4),
    "NO4": (69.6, 19.0),
    "NO5": (60.4, 5.3),
    "DK1": (56.0, 8.5),
    "DK2": (55.7, 12.0),
}

# Internal interconnectors (same as _INTERNAL_LINKS but with DB zone names).
_MAP_LINKS: list[tuple[str, str]] = [
    ("EE", "FI"), ("EE", "LV"), ("LV", "LT"),
    ("LT", "SE4"), ("FI", "SE3"),
    ("SE1", "SE2"), ("SE2", "SE3"), ("SE3", "SE4"),
    ("NO1", "NO2"), ("NO1", "NO3"), ("NO1", "NO5"),
    ("NO2", "NO5"), ("NO3", "NO4"), ("NO3", "NO5"),
    ("NO1", "SE3"), ("NO3", "SE2"), ("NO4", "SE1"),
    ("NO4", "SE2"), ("NO4", "FI"), ("FI", "SE1"),
    ("DK1", "DK2"), ("DK1", "NO2"), ("DK1", "SE3"), ("DK2", "SE4"),
]


def _arrowhead(lat1: float, lon1: float, lat2: float, lon2: float,
               frac: float = 0.35, spread: float = 0.4
               ) -> tuple[list[float | None], list[float | None]]:
    """Return lat/lon lists for a small arrowhead near the midpoint."""
    mx = (lat1 + lat2) / 2
    my = (lon1 + lon2) / 2
    dx = lat2 - lat1
    dy = lon2 - lon1
    length = math.hypot(dx, dy)
    if length == 0:
        return [mx], [my]
    ux, uy = dx / length, dy / length
    # Two wing points behind the midpoint
    bx = mx - ux * frac
    by = my - uy * frac
    px, py = -uy * spread, ux * spread
    return [mx, bx + px, None, mx, bx - px], [my, by + py, None, my, by - py]


def flow_map(con: duckdb.DuckDBPyConnection, start: str, end: str) -> go.Figure:
    """Map of Nordic-Baltic zones with interconnector flows."""
    # Fetch average net flow for each link.
    rows = con.execute(
        """
        SELECT from_zone, to_zone, avg(flow_mw) AS avg_mw
        FROM cross_border_flows
        WHERE period_start >= ? AND period_start < ?
        GROUP BY from_zone, to_zone
        """,
        [start, end],
    ).fetchall()

    # Build lookup: (from, to) -> avg MW.  Combine both directions into net.
    raw: dict[tuple[str, str], float] = {}
    for fz, tz, avg_mw in rows:
        raw[(fz, tz)] = avg_mw

    # For each link compute net flow (positive = from→to direction).
    link_flows: dict[tuple[str, str], float] = {}
    for a, b in _MAP_LINKS:
        fwd = raw.get((a, b), 0.0)
        rev = raw.get((b, a), 0.0)
        link_flows[(a, b)] = fwd - rev

    max_flow = max((abs(v) for v in link_flows.values()), default=1.0) or 1.0

    fig = go.Figure()

    # Draw interconnector lines.
    for (a, b), net in link_flows.items():
        lat_a, lon_a = _ZONE_COORDS[a]
        lat_b, lon_b = _ZONE_COORDS[b]

        # Color: blue = flow towards first zone, red = towards second.
        if abs(net) < 1:
            color = "gray"
            width = 1
        else:
            ratio = abs(net) / max_flow
            width = max(1.5, 5 * ratio)
            if net > 0:
                # Flow a→b: draw from a to b, red
                color = f"rgba(239,83,80,{0.3 + 0.7 * ratio})"
            else:
                # Flow b→a: draw from b to a, blue
                color = f"rgba(66,165,245,{0.3 + 0.7 * ratio})"

        direction = f"{a}→{b}" if net >= 0 else f"{b}→{a}"
        label = f"{direction}: {abs(net):.0f} MW avg"

        # Line segment.
        fig.add_trace(go.Scattergeo(
            lat=[lat_a, lat_b],
            lon=[lon_a, lon_b],
            mode="lines",
            line=dict(color=color, width=width),
            hoverinfo="text",
            text=label,
            showlegend=False,
        ))

        # Arrowhead pointing in flow direction.
        if abs(net) >= 1:
            if net > 0:
                ah_lat, ah_lon = _arrowhead(lat_a, lon_a, lat_b, lon_b)
            else:
                ah_lat, ah_lon = _arrowhead(lat_b, lon_b, lat_a, lon_a)
            fig.add_trace(go.Scattergeo(
                lat=ah_lat, lon=ah_lon,
                mode="lines",
                line=dict(color=color, width=width),
                hoverinfo="skip",
                showlegend=False,
            ))

    # Draw zone nodes.
    zone_lats = [c[0] for c in _ZONE_COORDS.values()]
    zone_lons = [c[1] for c in _ZONE_COORDS.values()]
    zone_names = list(_ZONE_COORDS.keys())
    fig.add_trace(go.Scattergeo(
        lat=zone_lats, lon=zone_lons,
        mode="markers+text",
        marker=dict(size=10, color="#1E88E5", line=dict(width=1, color="white")),
        text=zone_names,
        textposition="top center",
        textfont=dict(size=11, color="white"),
        hoverinfo="text",
        hovertext=zone_names,
        showlegend=False,
    ))

    fig.update_geos(
        scope="europe",
        projection_type="mercator",
        center=dict(lat=61, lon=16),
        lonaxis_range=[-2, 32],
        lataxis_range=[53, 72],
        showland=True,
        landcolor="#1a1a2e",
        showocean=True,
        oceancolor="#0d1b2a",
        showlakes=True,
        lakecolor="#0d1b2a",
        showcountries=True,
        countrycolor="#333",
        showcoastlines=True,
        coastlinecolor="#444",
    )
    fig.update_layout(
        title="Interconnector Flows (avg MW)",
        height=700,
        margin=dict(l=0, r=0, t=40, b=0),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font_color="white",
    )
    return fig
