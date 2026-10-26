"""Interactive figures over exported forecast data only."""

from operator import itemgetter

import pandas as pd
import plotly.graph_objects as go

from grid_signals.app.snapshot import MODEL_LABELS

TEAL = "#147d77"
AMBER = "#d28a25"


def fan_chart(
    series: dict,
    timezone: str,
    *,
    comparison: str | None = None,
    kind: str = "generation",
) -> go.Figure:
    utc = pd.to_datetime(series["time"], utc=True)
    local = utc.tz_convert(timezone)
    times = [value.isoformat() for value in utc]
    clock = [value.strftime("%d %b %H:%M %Z") for value in local]
    is_price = kind == "price"
    is_load = kind == "load"
    unit = "EUR/MWh" if is_price else "MW"
    suffix = "eur_mwh" if is_price else "mw"
    quantiles = series[f"quantiles_{suffix}"]
    fig = go.Figure()
    for lower, upper, label, opacity in (
        ("0.05", "0.95", "90% range", 0.09),
        ("0.10", "0.90", "80% range", 0.14),
        ("0.25", "0.75", "50% range", 0.22),
    ):
        fig.add_trace(
            go.Scatter(
                x=times,
                y=quantiles[lower],
                mode="lines",
                line={"width": 0},
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=times,
                y=quantiles[upper],
                mode="lines",
                line={"width": 0},
                fill="tonexty",
                fillcolor=f"rgba(20,125,119,{opacity})",
                name=label,
                hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=times,
            y=quantiles["0.50"],
            mode="lines",
            name="Forecast median",
            line={"color": TEAL, "width": 3},
            customdata=clock,
            hovertemplate="%{customdata}<br>%{y:,.1f} "
            + unit
            + "<extra>Forecast median</extra>",
        )
    )
    if f"actual_{suffix}" in series:
        fig.add_trace(
            go.Scatter(
                x=times,
                y=series[f"actual_{suffix}"],
                mode="lines",
                name="Actual spot price"
                if is_price
                else "Actual total load"
                if is_load
                else "Actual generation",
                line={"color": "#263b4a", "width": 2},
                customdata=clock,
                hovertemplate="%{customdata}<br>%{y:,.1f} "
                + unit
                + "<extra>Actual</extra>",
            )
        )
    if comparison:
        fig.add_trace(
            go.Scatter(
                x=times,
                y=series[f"comparisons_{suffix}"][comparison],
                mode="lines",
                name=MODEL_LABELS.get(comparison, comparison),
                line={"color": AMBER, "width": 2, "dash": "dot"},
                customdata=clock,
                hovertemplate="%{customdata}<br>%{y:,.1f} "
                + unit
                + "<extra>Comparison</extra>",
            )
        )
    fig.update_layout(
        height=410,
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "sans-serif", "color": "#435760"},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.12, "x": 0},
        xaxis={
            "title": f"Delivery time · {timezone}",
            "tickvals": times[::12],
            "ticktext": [value.strftime("%H:%M %Z") for value in local[::12]],
            "showgrid": False,
        },
        yaxis={
            "title": "Spot price · EUR/MWh"
            if is_price
            else "Total load · MW"
            if is_load
            else "Generation · MW",
            "rangemode": "normal" if is_price else "tozero",
            "gridcolor": "#e7ecea",
        },
    )
    if is_price:
        fig.add_hline(y=0, line_color="#aab7b3", line_dash="dot")
    return fig


def score_chart(task: dict) -> go.Figure:
    rows = sorted(task["evaluation"]["metrics"], key=itemgetter("crps"))
    fig = go.Figure(
        go.Bar(
            x=[row["crps"] * 100 for row in rows],
            y=[MODEL_LABELS.get(row["name"], row["name"]) for row in rows],
            orientation="h",
            marker_color=[
                TEAL if row["name"] == task["model"] else "#b6c7c4" for row in rows
            ],
            text=[f"{row['crps'] * 100:.2f}" for row in rows],
            textposition="outside",
            hovertemplate="%{x:.2f}% of capacity<extra></extra>",
        )
    )
    fig.update_layout(
        height=260,
        margin={"l": 0, "r": 45, "t": 10, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={
            "title": "CRPS · % of capacity (lower is better)",
            "gridcolor": "#e7ecea",
        },
        yaxis={"autorange": "reversed"},
        font={"color": "#435760"},
    )
    return fig
