"""Plotly figure builders for the dashboard."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import plotly.graph_objects as go

if TYPE_CHECKING:
    import duckdb


def hourly_prices(
    con: duckdb.DuckDBPyConnection, zones: list[str], start: str, end: str
) -> go.Figure:
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
            fig.add_trace(
                go.Scatter(x=times, y=prices, name=zone, mode="lines", line_shape="hv")
            )
    fig.update_layout(
        title="Day-Ahead Prices",
        xaxis_title="Time (UTC)",
        yaxis_title="EUR/MWh",
        legend_title="Zone",
        hovermode="x unified",
    )
    return fig


def generation_mix(
    con: duckdb.DuckDBPyConnection, zone: str, start: str, end: str
) -> go.Figure:
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
        fig.update_layout(
            title=f"Generation Mix — {zone}",
            annotations=[
                {
                    "text": "No data",
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                }
            ],
        )
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


def cross_border_flows(
    con: duckdb.DuckDBPyConnection, zone: str, start: str, end: str
) -> go.Figure:
    """Line chart of cross-border flows for all interconnections of a zone.

    For each neighbour, net flow = (zone->neighbour) - (neighbour->zone).
    Positive means export from the selected zone; negative means import.
    """
    rows = con.execute(
        """
        SELECT from_zone, to_zone, period_start, flow_mw
        FROM cross_border_flows
        WHERE (from_zone = ? OR to_zone = ?) AND period_start >= ? AND period_start < ?
        ORDER BY period_start
        """,
        [zone, zone, start, end],
    ).fetchall()

    # Build per-neighbour time series: {neighbour: {timestamp: net_mw}}
    neighbours: dict[str, dict] = {}
    for fz, tz, ts, mw in rows:
        if fz == zone:
            nbr = tz
            neighbours.setdefault(nbr, {})[ts] = (
                neighbours.get(nbr, {}).get(ts, 0.0) + mw
            )
        else:
            nbr = fz
            neighbours.setdefault(nbr, {})[ts] = (
                neighbours.get(nbr, {}).get(ts, 0.0) - mw
            )

    display = _display_zone  # short alias
    fig = go.Figure()
    for nbr in sorted(neighbours):
        series = neighbours[nbr]
        times = sorted(series)
        flows = [series[t] for t in times]
        fig.add_trace(
            go.Scatter(
                x=times,
                y=flows,
                mode="lines",
                name=f"{display(zone)} ↔ {display(nbr)}",
                line_shape="hv",
            )
        )

    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        title=f"Cross-Border Flows: {display(zone)}",
        xaxis_title="Time (UTC)",
        yaxis_title=f"MW (positive = export from {display(zone)})",
        hovermode="x unified",
    )
    return fig


def _display_zone(code: str) -> str:
    """Convert DB zone code to display label (e.g. 'SE_4' → 'SE4')."""
    return code.replace("_", "")


def wind_vs_price(
    con: duckdb.DuckDBPyConnection, zone: str, location: str, start: str, end: str
) -> go.Figure:
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
            go.Scatter(
                x=[r[0] for r in weather],
                y=[r[1] for r in weather],
                name="Wind (m/s)",
                mode="lines",
                line={"color": "#26A69A"},
                line_shape="hv",
            ),
            secondary_y=False,
        )
    if prices:
        fig.add_trace(
            go.Scatter(
                x=[r[0] for r in prices],
                y=[r[1] for r in prices],
                name="Price (EUR/MWh)",
                mode="lines",
                line={"color": "#EF5350"},
                line_shape="hv",
            ),
            secondary_y=True,
        )
    fig.update_layout(
        title=f"Wind vs Price — {zone} / {location}",
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Wind Speed (m/s)", secondary_y=False)
    fig.update_yaxes(title_text="EUR/MWh", secondary_y=True)
    return fig


def price_heatmap(
    con: duckdb.DuckDBPyConnection, zones: list[str], date: str
) -> go.Figure:
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
        fig.update_layout(
            title="Price Heatmap",
            annotations=[
                {
                    "text": "No data",
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                }
            ],
        )
        return fig

    zone_data: dict[str, dict[int, float]] = {}
    for zone, hour, price in rows:
        zone_data.setdefault(zone, {})[int(hour)] = price

    zone_labels = sorted(zone_data.keys())
    hours = list(range(24))
    z = [[zone_data.get(z, {}).get(h, None) for h in hours] for z in zone_labels]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=[f"{h:02d}:00" for h in hours],
            y=zone_labels,
            colorscale="RdYlGn_r",
            colorbar_title="EUR/MWh",
        )
    )
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
    ("EE", "FI"),
    ("EE", "LV"),
    ("LV", "LT"),
    ("LT", "SE4"),
    ("FI", "SE3"),
    ("SE1", "SE2"),
    ("SE2", "SE3"),
    ("SE3", "SE4"),
    ("NO1", "NO2"),
    ("NO1", "NO3"),
    ("NO1", "NO5"),
    ("NO2", "NO5"),
    ("NO3", "NO4"),
    ("NO3", "NO5"),
    ("NO1", "SE3"),
    ("NO3", "SE2"),
    ("NO4", "SE1"),
    ("NO4", "SE2"),
    ("NO4", "FI"),
    ("FI", "SE1"),
    ("DK1", "DK2"),
    ("DK1", "NO2"),
    ("DK1", "SE3"),
    ("DK2", "SE4"),
]


def _arrow_triangle(
    src_lat: float,
    src_lon: float,
    dst_lat: float,
    dst_lon: float,
    pos: float = 0.55,
    size: float = 0.25,
    width: float = 0.12,
) -> tuple[list[float], list[float]]:
    """Filled-arrowhead triangle at *pos* fraction along the line."""
    tip_lat = src_lat + pos * (dst_lat - src_lat)
    tip_lon = src_lon + pos * (dst_lon - src_lon)
    dlat = dst_lat - src_lat
    dlon = dst_lon - src_lon
    length = math.hypot(dlat, dlon)
    if length < 0.01:
        return [], []
    ulat, ulon = dlat / length, dlon / length
    base_lat = tip_lat - ulat * size
    base_lon = tip_lon - ulon * size
    return (
        [base_lat - ulon * width, tip_lat, base_lat + ulon * width],
        [base_lon + ulat * width, tip_lon, base_lon - ulat * width],
    )


def _label_pos(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    offset: float = 0.25,
) -> tuple[float, float]:
    """Midpoint shifted perpendicular to the line for label placement."""
    mid_lat = (lat1 + lat2) / 2
    mid_lon = (lon1 + lon2) / 2
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    length = math.hypot(dlat, dlon)
    if length < 0.01:
        return mid_lat, mid_lon
    return mid_lat + (-dlon / length) * offset, mid_lon + (dlat / length) * offset


def flow_map(con: duckdb.DuckDBPyConnection, start: str, end: str) -> go.Figure:
    """Map of Nordic-Baltic zones with interconnector flows on real geography."""
    rows = con.execute(
        """
        SELECT from_zone, to_zone, avg(flow_mw) AS avg_mw
        FROM cross_border_flows
        WHERE period_start >= ? AND period_start < ?
        GROUP BY from_zone, to_zone
        """,
        [start, end],
    ).fetchall()

    raw: dict[tuple[str, str], float] = {}
    for fz, tz, avg_mw in rows:
        raw[fz, tz] = avg_mw

    link_flows: dict[tuple[str, str], float] = {}
    for a, b in _MAP_LINKS:
        fwd = raw.get((a, b), 0.0)
        rev = raw.get((b, a), 0.0)
        link_flows[a, b] = fwd - rev

    max_flow = max((abs(v) for v in link_flows.values()), default=1.0) or 1.0

    fig = go.Figure()

    label_lats: list[float] = []
    label_lons: list[float] = []
    label_texts: list[str] = []

    for (a, b), net in link_flows.items():
        lat_a, lon_a = _ZONE_COORDS[a]
        lat_b, lon_b = _ZONE_COORDS[b]
        abs_net = abs(net)
        ratio = abs_net / max_flow
        width = max(2.0, 5.0 * ratio)

        if abs_net < 1:
            color = "rgba(0,121,107,0.25)"
        else:
            color = f"rgba(0,121,107,{0.35 + 0.65 * ratio})"

        # Orient source→destination along net flow direction.
        if net >= 0:
            s_lat, s_lon, d_lat, d_lon = lat_a, lon_a, lat_b, lon_b
            direction = f"{a}→{b}"
        else:
            s_lat, s_lon, d_lat, d_lon = lat_b, lon_b, lat_a, lon_a
            direction = f"{b}→{a}"

        hover = f"{direction}: {abs_net:.0f} MW avg"

        # Flow line.
        fig.add_trace(
            go.Scattermapbox(
                lat=[s_lat, d_lat],
                lon=[s_lon, d_lon],
                mode="lines",
                line={"color": color, "width": width},
                hovertext=hover,
                hoverinfo="text",
                showlegend=False,
            )
        )

        # Filled arrowhead triangle.
        if abs_net >= 1:
            ah_lat, ah_lon = _arrow_triangle(s_lat, s_lon, d_lat, d_lon)
            if ah_lat:
                fig.add_trace(
                    go.Scattermapbox(
                        lat=ah_lat,
                        lon=ah_lon,
                        mode="lines",
                        line={"color": color, "width": 1},
                        fill="toself",
                        fillcolor=color,
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

            # Collect MW label at offset midpoint.
            ol, on = _label_pos(s_lat, s_lon, d_lat, d_lon)
            label_lats.append(ol)
            label_lons.append(on)
            label_texts.append(f"{abs_net:.0f}")

    # MW labels — single trace for performance.
    if label_lats:
        fig.add_trace(
            go.Scattermapbox(
                lat=label_lats,
                lon=label_lons,
                mode="text",
                text=label_texts,
                textfont={"size": 11, "color": "#004D40", "family": "Arial Black"},
                hoverinfo="skip",
                showlegend=False,
            )
        )

    # Zone markers.
    zone_lats = [c[0] for c in _ZONE_COORDS.values()]
    zone_lons = [c[1] for c in _ZONE_COORDS.values()]
    zone_names = list(_ZONE_COORDS.keys())
    fig.add_trace(
        go.Scattermapbox(
            lat=zone_lats,
            lon=zone_lons,
            mode="markers+text",
            marker={"size": 10, "color": "#1565C0", "opacity": 0.9},
            text=zone_names,
            textfont={"size": 12, "color": "#0D47A1", "family": "Arial Black"},
            textposition="top center",
            hoverinfo="text",
            hovertext=zone_names,
            showlegend=False,
        )
    )

    fig.update_layout(
        mapbox={
            "style": "carto-positron",
            "center": {"lat": 62, "lon": 16},
            "zoom": 3.5,
        },
        title="Interconnector Flows (avg MW)",
        height=700,
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
    )
    return fig
