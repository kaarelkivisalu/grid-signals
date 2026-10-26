"""Linked fundamentals, uncertainty, errors and an offline European coverage map."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from grid_signals.app.explorer_data import complete_hourly
from grid_signals.app.markets import MARKETS, TARGETS
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
    figure.update_yaxes(title_text="Power · GW", row=1, col=1)
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
) -> go.Figure:
    figure = go.Figure()
    times = pd.DatetimeIndex(rows.valid_time)
    for lo, hi, opacity, label in (
        ("0.05", "0.95", 0.07, "90% interval"),
        ("0.10", "0.90", 0.13, "80% interval"),
        ("0.25", "0.75", 0.22, "50% interval"),
    ):
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
                fillcolor=f"rgba(22,143,135,{opacity})",
                name=label,
                hoverinfo="skip",
            )
        )
    figure.add_trace(
        go.Scatter(
            x=times,
            y=rows["q0.50"],
            name="Median",
            line={"color": "#168f87", "width": 2.5},
        )
    )
    if rows.actual.notna().any():
        figure.add_trace(
            go.Scatter(
                x=times,
                y=rows.actual,
                name="Actual",
                line={"color": "#263c48", "width": 2},
            )
        )
    if comparison is not None and not comparison.empty:
        aligned = comparison.set_index("valid_time").reindex(times)
        figure.add_trace(
            go.Scatter(
                x=times,
                y=aligned["q0.50"],
                name=model_name(comparison.model.iloc[0]),
                line={"color": "#c58c30", "dash": "dot"},
            )
        )
    figure.update_yaxes(title_text="EUR/MWh" if target == "price" else "MW")
    local_axis(figure, times, timezone)
    return style(figure, 470)


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


def coverage_map(manifest: dict, selected: str) -> go.Figure:
    """Bundled country outlines with clickable zone anchors; no remote map tiles."""
    figure = go.Figure()
    payload = json.loads(
        (Path(__file__).parent / "assets/explorer/europe.geojson").read_text()
    )
    for feature in payload["features"]:
        geometry = feature["geometry"]
        polygons = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        for polygon in polygons:
            coordinates = np.asarray(polygon[0])
            figure.add_trace(
                go.Scatter(
                    x=coordinates[:, 0],
                    y=_mercator(coordinates[:, 1]),
                    mode="lines",
                    line={"width": 0.5, "color": "#cbd5cf"},
                    fill="toself",
                    fillcolor="#eef2ee",
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
    groups = {
        "Project data / forecasts": ("#168f87", "circle"),
        "SDAC · not yet imported": ("#c99538", "circle-open"),
        "Outside SDAC": ("#82919a", "diamond"),
    }
    for label, (color, symbol) in groups.items():
        chosen = [
            m
            for m in MARKETS
            if (
                "Outside SDAC"
                if not m.sdac
                else "Project data / forecasts"
                if m.code in manifest["zones"]
                else "SDAC · not yet imported"
            )
            == label
        ]
        figure.add_trace(
            go.Scatter(
                x=[m.lon for m in chosen],
                y=[_mercator(m.lat) for m in chosen],
                customdata=[m.code for m in chosen],
                text=[m.code.replace("_", "-") for m in chosen],
                mode="markers+text"
                if label == "Project data / forecasts"
                else "markers",
                textposition="top center",
                textfont={"size": 11},
                marker={
                    "size": [17 if m.code == selected else 10 for m in chosen],
                    "color": color,
                    "symbol": symbol,
                    "line": {"width": 2},
                },
                name=label,
                hovertext=[
                    f"{m.code} · {m.name}<br>{'Custom models + observations' if manifest['zones'].get(m.code, {}).get('targets') else 'Bundled observations' if m.code in manifest['zones'] else label}"
                    for m in chosen
                ],
                hovertemplate="%{hovertext}<extra></extra>",
            )
        )
    style(figure, 620)
    figure.update_layout(
        hovermode="closest",
        dragmode="pan",
        clickmode="event+select",
        legend={"orientation": "h", "y": -0.04, "x": 0},
    )
    figure.update_xaxes(range=[-23, 39], visible=False, fixedrange=False)
    figure.update_yaxes(
        range=[_mercator(34), _mercator(71)],
        visible=False,
        scaleanchor="x",
        scaleratio=1,
    )
    return figure
