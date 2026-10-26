"""Linked fundamentals, uncertainty, errors and an offline European coverage map."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from grid_signals.app.explorer_data import complete_hourly
from grid_signals.app.markets import COUNTRY_MARKETS, TARGETS
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


def fundamentals_chart(
    observed: pd.DataFrame,
    curves: dict[str, pd.DataFrame],
    timezone: str,
    series: list[str],
    *,
    hourly: bool = False,
) -> go.Figure:
    frame = complete_hourly(observed) if hourly else observed
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.12,
        row_heights=[0.62, 0.38],
    )
    for target in series:
        if target in frame and frame[target].notna().any():
            figure.add_trace(
                go.Scatter(
                    x=frame.index,
                    y=frame[target] / 1000,
                    name=LABELS[target],
                    legendgroup=target,
                    line={"color": COLORS[target], "width": 2},
                    connectgaps=False,
                ),
                row=1,
                col=1,
            )
    if "price" in frame and frame.price.notna().any():
        figure.add_trace(
            go.Scatter(
                x=frame.index,
                y=frame.price,
                name="Spot price",
                legendgroup="price",
                line={"color": COLORS["price"], "width": 2},
            ),
            row=2,
            col=1,
        )
    for target, curve in curves.items():
        if curve.empty or (target != "price" and target not in series):
            continue
        median = curve.set_index("valid_time")[["q0.50"]]
        median = complete_hourly(median) if hourly else median
        row = 2 if target == "price" else 1
        scale = 1 if target == "price" else 1000
        figure.add_trace(
            go.Scatter(
                x=median.index,
                y=median["q0.50"] / scale,
                name=f"{LABELS[target]} · forecast",
                legendgroup=target,
                showlegend=target not in frame or not frame[target].notna().any(),
                line={"color": COLORS[target], "dash": "dash", "width": 2},
            ),
            row=row,
            col=1,
        )
    figure.update_yaxes(title_text="Generation & demand · GW", row=1, col=1)
    figure.update_yaxes(title_text="Spot · EUR/MWh", row=2, col=1)
    style(figure, 590)
    local_axis(figure, frame.index, timezone)
    figure.update_xaxes(title_text=None, row=1, col=1)
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
                + ": %{y:.2f}<extra></extra>",
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
    return figure


def error_chart(rows: pd.DataFrame, timezone: str, target: str) -> go.Figure:
    figure = go.Figure(
        go.Bar(
            x=rows.valid_time,
            y=rows["q0.50"] - rows.actual,
            marker_color="#c85d43",
            name="Forecast - actual",
        )
    )
    local_axis(figure, pd.DatetimeIndex(rows.valid_time), timezone)
    figure.update_yaxes(
        title_text="Error · EUR/MWh" if target == "price" else "Error · MW"
    )
    return style(figure, 230)


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


def price_relationship(frame: pd.DataFrame) -> go.Figure:
    figure = go.Figure(
        go.Scatter(
            x=frame.residual_load / 1000,
            y=frame.price,
            mode="markers",
            name="Observed intervals",
            marker={
                "size": 6,
                "color": frame.solar / 1000,
                "colorscale": "YlOrBr",
                "showscale": True,
                "colorbar": {"title": "Solar GW"},
                "opacity": 0.65,
            },
            text=frame.index.strftime("%Y-%m-%d %H:%M UTC"),
            hovertemplate="%{text}<br>Residual %{x:.2f} GW<br>Spot %{y:.2f} EUR/MWh<extra></extra>",
        )
    )
    figure.update_xaxes(title_text="Observed residual load · GW")
    figure.update_yaxes(title_text="Day-ahead spot · EUR/MWh")
    return style(figure, 360).update_layout(hovermode="closest", showlegend=False)


def _mercator(latitude):
    return np.degrees(np.log(np.tan(np.pi / 4 + np.radians(latitude) / 2)))


def coverage_map(manifest: dict) -> go.Figure:
    """Shade relevant countries using local polygons, without remote map tiles."""
    figure = go.Figure()
    payload = json.loads(
        (Path(__file__).parent / "assets/explorer/europe.geojson").read_text()
    )
    colors = {
        "Evaluated forecasts": "#4f9e92",
        "Observations only": "#c7ddd5",
        "Planned": "#e3e8e5",
    }
    shown = set()
    for feature in payload["features"]:
        country = feature["properties"]["name"]
        if country not in COUNTRY_MARKETS:
            continue
        zones = COUNTRY_MARKETS[country]
        info = [manifest["zones"].get(zone, {}) for zone in zones]
        status = (
            "Evaluated forecasts"
            if any(item.get("targets") for item in info)
            else "Observations only"
            if any(item.get("observations") for item in info)
            else "Planned"
        )
        detail = ", ".join(
            zone.replace("_", "-")
            for zone, item in zip(zones, info, strict=True)
            if item.get("targets")
        )
        hover = f"{country}<br>{status}"
        if detail:
            hover += f" in {detail}<br>Other zones/targets may still be unavailable"
        geometry = feature["geometry"]
        polygons = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        for polygon in polygons:
            coordinates = np.asarray(polygon[0])
            # Omit far-northern islands outside the electricity-market view.
            if coordinates[:, 1].min() > 72:
                continue
            figure.add_trace(
                go.Scatter(
                    x=coordinates[:, 0],
                    y=_mercator(coordinates[:, 1]),
                    mode="lines",
                    line={"width": 1, "color": "#f8faf9"},
                    fill="toself",
                    fillcolor=colors[status],
                    name=status,
                    legendgroup=status,
                    showlegend=status not in shown,
                    text=hover,
                    hovertemplate="%{text}<extra></extra>",
                    hoveron="fills",
                    meta={"country": country, "status": status},
                )
            )
            shown.add(status)
    labels = {
        "Sweden": (16, 63),
        "Norway": (9, 61),
        "Finland": (26, 65),
        "Denmark": (9.5, 56.5),
        "Estonia": (26, 59),
        "Latvia": (25.5, 57),
        "Lithuania": (25, 55.3),
        "Germany": (10.5, 51.5),
    }
    figure.add_trace(
        go.Scatter(
            x=[point[0] for point in labels.values()],
            y=[_mercator(point[1]) for point in labels.values()],
            text=list(labels),
            mode="text",
            textfont={"size": 12, "color": "#24483f"},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    style(figure, 610)
    figure.update_layout(
        hovermode="closest",
        dragmode=False,
        margin={"l": 0, "r": 0, "t": 10, "b": 40},
        legend={"orientation": "h", "y": -0.02, "x": 0},
    )
    figure.update_xaxes(range=[3, 33], visible=False, fixedrange=True)
    figure.update_yaxes(
        range=[_mercator(47), _mercator(71.5)],
        visible=False,
        scaleanchor="x",
        scaleratio=1,
        fixedrange=True,
    )
    return figure
