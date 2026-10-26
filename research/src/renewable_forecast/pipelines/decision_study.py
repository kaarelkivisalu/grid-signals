"""Exploratory flexible-consumption study over the frozen price development forecasts."""

import json

import numpy as np
import pandas as pd

from renewable_forecast import paths
from renewable_forecast.evaluation.splits import bootstrap_ci
from renewable_forecast.pipelines import price

OUTPUT = paths.INTERIM / "price_decision_study.json"


def dispatch(predicted: np.ndarray) -> np.ndarray:
    """Allocate 1 MWh into eight intervals, respecting a 0.5 MW power limit."""
    if len(predicted) < 8 or not np.isfinite(predicted).all():
        raise ValueError("dispatch needs at least eight finite quarter-hour prices")
    energy = np.zeros(len(predicted))
    energy[np.argsort(predicted, kind="stable")[:8]] = 0.125
    return energy


def build(frame: pd.DataFrame) -> dict:
    if (frame.delivery_day >= pd.Timestamp("2026-09-01")).any():
        raise ValueError("decision study must not open the sealed price holdout")
    rows = []
    for (name, day), group in frame.groupby(["forecaster", "delivery_day"]):
        context = group.sort_values("valid_time")
        actual = context.price.to_numpy()
        rows.append(
            {
                "method": name,
                "day": day,
                "cost": float(dispatch(context["q0.50"].to_numpy()) @ actual),
                "uniform": float(actual.mean()),
                "oracle": float(dispatch(actual) @ actual),
            }
        )
    daily = pd.DataFrame(rows)
    methods = []
    for name, group in daily.groupby("method"):
        savings = group.uniform - group.cost
        low, high = bootstrap_ci(savings, group.day)
        methods.append(
            {
                "Method": name,
                "Days": len(group),
                "Mean daily energy cost (EUR)": round(float(group.cost.mean()), 2),
                "Saving vs uniform (EUR/day)": round(float(savings.mean()), 2),
                "95% saving CI low": round(float(low), 2),
                "95% saving CI high": round(float(high), 2),
            }
        )
    reference = daily[daily.method == daily.method.iloc[0]]
    for name, column in [
        ("Uniform consumption", "uniform"),
        ("Perfect information", "oracle"),
    ]:
        methods.append(
            {
                "Method": name,
                "Days": len(reference),
                "Mean daily energy cost (EUR)": round(
                    float(reference[column].mean()), 2
                ),
                "Saving vs uniform (EUR/day)": round(
                    float((reference.uniform - reference[column]).mean()), 2
                ),
                "95% saving CI low": None,
                "95% saving CI high": None,
            }
        )
    return {
        "status": "exploratory development simulation",
        "energy_mwh_per_day": 1,
        "power_limit_mw": 0.5,
        "selected_quarter_hours": 8,
        "interruptions_allowed": True,
        "costs_excluded": ["transaction fees", "grid charges", "taxes"],
        "methods": methods,
    }


def write() -> dict:
    result = build(pd.read_parquet(price.BACKTEST))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, allow_nan=False))
    return result


if __name__ == "__main__":
    print(json.dumps(write(), indent=2))
