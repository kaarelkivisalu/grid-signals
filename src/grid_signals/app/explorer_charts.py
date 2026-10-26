"""Overview time series, forecast errors and an offline market-area map."""

import json
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from grid_signals.app.markets import BY_CODE, TARGETS
from grid_signals.app.model_catalogue import model_name

COLORS = {
    "load": "#344957",
    "solar": "#d7981d",
    "wind_onshore": "#168f87",
    "wind_offshore": "#65b7b0",
    "residual_load": "#8664ad",
    "price": "#c85d43",
}
LABELS = {**TARGETS, "wind_offshore": "Offshore wind"}


def style(figure: go.Figure, height: int = 500) -> go.Figure:
    figure.update_layout(
        template="plotly_white",
        height=height,
        margin={"l": 12, "r": 12, "t": 20, "b": 100},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Arial, sans-serif", "color": "#344957"},
        legend={"orientation": "h", "y": -0.24, "x": 0},
        hovermode="x unified",
    )
    figure.update_xaxes(showgrid=False)
    figure.update_yaxes(gridcolor="#e4eae7", zerolinecolor="#b2c5bd")
    return figure


def local_axis(figure: go.Figure, index: pd.DatetimeIndex, timezone: str) -> None:
    if index.empty:
        return
    wall = index.tz_convert(timezone)
    ticks = index[(wall.hour % 6 == 0) & (wall.minute == 0)]
    if ticks.empty:
        ticks = index[:1]
    local = ticks.tz_convert(timezone)
    figure.update_xaxes(
        tickvals=ticks,
        ticktext=local.strftime("%H:%M<br>%Z"),
        title_text="Delivery time",
        hoverformat="%Y-%m-%d %H:%M UTC",
    )


def overview_chart(
    observed: pd.DataFrame,
    curves: dict[str, pd.DataFrame],
    timezone: str,
    products: list[str],
) -> go.Figure:
    """Combine products on one unit axis, retaining at most one forecast each."""
    figure = go.Figure()
    price = products == ["price"]
    for product in products:
        label = LABELS[product]
        color = COLORS[product]
        if product in observed and observed[product].notna().any():
            figure.add_trace(
                go.Scatter(
                    x=observed.index,
                    y=observed[product],
                    name=f"{label} · actual",
                    legendgroup=product,
                    line={"color": color, "width": 2},
                    connectgaps=False,
                    meta={"product": product, "kind": "actual"},
                )
            )
        curve = curves.get(product)
        if curve is not None and not curve.empty:
            figure.add_trace(
                go.Scatter(
                    x=curve.valid_time,
                    y=curve["q0.50"],
                    name=f"{label} · forecast",
                    legendgroup=product,
                    line={"color": color, "width": 2.5, "dash": "dash"},
                    meta={
                        "product": product,
                        "kind": "forecast",
                        "model": curve.model.iloc[0],
                    },
                )
            )
    style(figure, 310 if price else 380)
    local_axis(figure, observed.index, timezone)
    figure.update_xaxes(title_text=None, showgrid=True, gridcolor="#e4e8e8")
    figure.update_yaxes(
        title_text="EUR/MWh" if price else "MW",
        tickformat=None if price else ",.0f",
        hoverformat=".2f" if price else ",.0f",
    )
    figure.update_layout(
        margin={"l": 12, "r": 12, "t": 8, "b": 100},
        legend={"orientation": "h", "y": -0.25, "x": 0},
        showlegend=True,
    )
    return figure


def forecast_chart(
    rows: pd.DataFrame,
    timezone: str,
    target: str,
    comparison: pd.DataFrame | None = None,
    *,
    full_intervals: bool = False,
    show_error: bool = False,
) -> go.Figure:
    has_error = show_error and rows.actual.notna().any()
    figure = make_subplots(
        rows=2 if has_error else 1,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.75, 0.25] if has_error else [1],
    )
    times = pd.DatetimeIndex(rows.valid_time)
    for lo, hi, opacity, label in (
        ("0.05", "0.95", 0.07, "90% range"),
        ("0.10", "0.90", 0.13, "80% range"),
        ("0.25", "0.75", 0.22, "50% range"),
    ):
        if not full_intervals and label != "80% range":
            continue
        figure.add_trace(
            go.Scatter(
                x=times,
                y=rows[f"q{lo}"],
                mode="lines",
                line={"width": 0},
                showlegend=False,
                hoverinfo="skip",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=times,
                y=rows[f"q{hi}"],
                mode="lines",
                line={"width": 0},
                fill="tonexty",
                fillcolor=f"rgba(96,157,180,{opacity})",
                legendrank=40,
                name=label,
                hoverinfo="skip",
            )
        )
    figure.add_trace(
        go.Scatter(
            x=times,
            y=rows["q0.50"],
            name="Forecast",
            line={"color": "#b65753", "width": 2.5},
            legendrank=10,
        )
    )
    if rows.actual.notna().any():
        figure.add_trace(
            go.Scatter(
                x=times,
                y=rows.actual,
                name="Actual",
                line={"color": "#20292f", "width": 2},
                legendrank=20,
            )
        )
    if comparison is not None and not comparison.empty:
        aligned = comparison.set_index("valid_time").reindex(times)
        figure.add_trace(
            go.Scatter(
                x=times,
                y=aligned["q0.50"],
                name="Reference",
                hovertemplate=model_name(comparison.model.iloc[0])
                + (": %{y:.2f}" if target == "price" else ": %{y:,.0f} MW")
                + "<extra></extra>",
                line={"color": "#85916c", "dash": "dot"},
                legendrank=30,
            )
        )
    figure.update_yaxes(title_text="EUR/MWh" if target == "price" else "MW")
    local_axis(figure, times, timezone)
    style(figure, 620 if has_error else 470)
    figure.update_layout(
        plot_bgcolor="#ffffff",
        margin={"l": 12, "r": 12, "t": 12, "b": 70},
        legend={"orientation": "h", "y": -0.13, "x": 0, "traceorder": "normal"},
    )
    figure.update_xaxes(
        showgrid=True, gridcolor="#e4e8e8", showline=True, linecolor="#b8c4c4"
    )
    figure.update_yaxes(gridcolor="#e4e8e8", showline=True, linecolor="#b8c4c4")
    if not has_error:
        figure.update_xaxes(title_text=None)
    if has_error:
        figure.add_trace(
            go.Scatter(
                x=times,
                y=rows["q0.50"] - rows.actual,
                name="Forecast - actual",
                showlegend=False,
                line={"color": "#4e6b80", "width": 1.5},
            ),
            row=2,
            col=1,
        )
        figure.add_hline(y=0, line_color="#8d9c9c", line_width=1, row=2, col=1)
        figure.update_yaxes(
            title_text="Error · " + ("EUR/MWh" if target == "price" else "MW"),
            row=2,
            col=1,
        )
        figure.update_xaxes(title_text=None, showticklabels=False, row=1, col=1)
    if target != "price":
        figure.update_yaxes(tickformat=",.0f", hoverformat=",.0f")
    return figure


def diagnostic_chart(scores: pd.DataFrame, metric: str) -> go.Figure:
    figure = go.Figure()
    if scores.Group.eq(scores.Group.iloc[0]).all():
        figure.add_trace(
            go.Bar(
                x=scores.model.map(model_name),
                y=scores[metric],
                marker_color="#168f87",
                showlegend=False,
            )
        )
    else:
        for (split, model), rows in scores.groupby(["split", "model"], sort=False):
            figure.add_trace(
                go.Scatter(
                    x=rows.Group,
                    y=rows[metric],
                    mode="lines+markers",
                    name=f"{model_name(model)} · {split}",
                )
            )
    if metric == "Coverage80":
        figure.add_hline(y=80, line_dash="dot", annotation_text="Nominal 80%")
    if metric == "Coverage90":
        figure.add_hline(y=90, line_dash="dot", annotation_text="Nominal 90%")
    return style(figure, 390)


def _mercator(latitude):
    return np.degrees(np.log(np.tan(np.pi / 4 + np.radians(latitude) / 2)))


def coverage_map(manifest: dict) -> str:
    """A fixed, linked SVG map: every SDAC area stays visible."""
    payload = json.loads(
        (Path(__file__).parent / "assets/explorer/market-areas.geojson").read_text()
    )
    colors = {
        "Evaluated forecasts": "#76b5a3",
        "Observations only": "#b5ccde",
        "Not available": "#e3e8e5",
    }
    west, north, scale = -12, float(_mercator(72)), 8.5
    parts = [
        (
            '<svg class="market-map" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 600" '
            'role="group" aria-label="SDAC market areas; open an area to view its data" '
            'style="display:block;width:100%;height:auto;max-height:780px">'
        ),
        (
            "<style>.market-map a:hover path,.market-map a:focus path{stroke:#183c3b;stroke-width:2} "
            ".market-map a,.market-map text{text-decoration:none!important} "
            ".market-map text{font:11px Arial,sans-serif;fill:#24483f} "
            ".market-map path{stroke:#6e8481;stroke-width:.7;vector-effect:non-scaling-stroke}</style>"
        ),
    ]
    for feature in payload["features"]:
        zone = feature["properties"]["zone"]
        info = manifest["zones"].get(zone, {})
        status = (
            "Evaluated forecasts"
            if info.get("targets")
            else "Observations only"
            if info.get("observations")
            else "Not available"
        )
        geometry = feature["geometry"]
        polygons = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        rings = []
        for polygon in polygons:
            for ring in polygon:
                points = [
                    f"{(lon - west) * scale:.2f},{(north - float(_mercator(lat))) * scale:.2f}"
                    for lon, lat in ring
                ]
                rings.append("M" + "L".join(points) + "Z")
        label = zone.replace("_", "-")
        title = escape(f"{label} · {BY_CODE[zone].name} · {status}")
        lon, lat = feature["properties"]["label"]
        # The Italian zone suffixes stay readable within their smaller shapes.
        text = label.removeprefix("IT-")
        parts.append(
            f'<a href="/?area={zone}" target="_self" tabindex="0" aria-label="{title}">'
            f'<title>{title}</title><path data-zone="{zone}" data-status="{status}" '
            f'd="{"".join(rings)}" fill="{colors[status]}" fill-rule="evenodd"/>'
            f'<text x="{(lon - west) * scale:.2f}" y="{(north - float(_mercator(lat))) * scale:.2f}" '
            f'text-anchor="middle" dominant-baseline="middle">{text}</text></a>'
        )
    parts.append(
        '</svg><div style="display:flex;flex-wrap:wrap;gap:1rem;font:13px Arial,sans-serif;color:#344957">'
    )
    for status, color in colors.items():
        parts.append(
            f'<span><span style="display:inline-block;width:.8rem;height:.8rem;background:{color};margin-right:.4rem"></span>{status}</span>'
        )
    parts.append("</div>")
    return "".join(parts)
