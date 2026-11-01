"""Portable price preview from completed benchmark and publication artifacts."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from grid_signals.forecast import paths
from grid_signals.forecast.pipelines import price

OUTPUT = paths.OUTPUT / "price_snapshot.json"
LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def series(frame: pd.DataFrame, *, forecast: bool = False) -> dict:
    prefix = "eur_mwh_q" if forecast else "q"
    return {
        "time": [value.isoformat() for value in frame.valid_time],
        "quantiles_eur_mwh": {
            f"{q:.2f}": frame[f"{prefix}{q:.2f}"].round(3).tolist() for q in LEVELS
        },
    }


def build() -> dict:
    frame = pd.read_parquet(price.BACKTEST)
    table = pd.read_parquet(price.METRICS)
    candidate = frame[frame.forecaster == "lightgbm_quantile"].copy()
    candidate["error"] = (candidate.price - candidate["q0.50"]).abs()
    errors = candidate.groupby("delivery_day").error.mean().sort_values()
    if (candidate.delivery_day >= pd.Timestamp("2026-09-01")).any():
        raise ValueError("price preview cannot expose the sealed price holdout")
    examples = []
    for label, fraction in [
        ("Typical day", 0.5),
        ("Difficult day", 0.9),
        ("Largest error", 1),
    ]:
        day = errors.index[round((len(errors) - 1) * fraction)]
        rows = candidate[candidate.delivery_day == day].sort_values("valid_time")
        references = {}
        for name, group in frame[frame.delivery_day == day].groupby("forecaster"):
            if name != "lightgbm_quantile":
                references[name] = (
                    group.set_index("valid_time")
                    .reindex(rows.valid_time)["q0.50"]
                    .round(3)
                    .tolist()
                )
        examples.append(
            {
                "label": label,
                "delivery_date": day.date().isoformat(),
                "mae": float(errors.loc[day]),
                **series(rows),
                "actual_eur_mwh": rows.price.round(3).tolist(),
                "comparisons_eur_mwh": references,
            }
        )
    forecast = None
    if price.VINTAGES.exists():
        vintages = pd.read_parquet(price.VINTAGES)
        rows = vintages[vintages.created_at == vintages.created_at.max()].sort_values(
            "valid_time"
        )
        head = rows.iloc[0]
        forecast = {
            **series(rows, forecast=True),
            "forecast_id": head.forecast_id,
            "delivery_date": head.delivery_day.date().isoformat(),
            "cutoff_at": head.information_cutoff_at.isoformat(),
            "created_at": head.created_at.isoformat(),
            "published_at": head.published_at.isoformat(),
            "publication_status": head.publication_status,
            "model_version": head.model_version,
            "forecaster": head.get("forecaster", "lightgbm_quantile"),
            "temporal_method": head.get("temporal_method", "native"),
        }
    decision = paths.INTERIM / "price_decision_study.json"
    final = paths.DATA / "holdout_price_2026_10_15/result.json"
    live = paths.DATA / "operational/price_scorecard.json"
    protocol = paths.INTERIM / "price_protocol.json"
    inputs = paths.INTERIM / "price_load_metrics.json"
    return {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "zone": "DE_LU",
        "unit": "EUR/MWh",
        "load_input_experiment": json.loads(inputs.read_text())
        if inputs.exists()
        else None,
        "sources": {
            str(path.relative_to(paths.DATA)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in [price.BACKTEST, price.METRICS]
        },
        "protocol": json.loads(protocol.read_text()) if protocol.exists() else None,
        "forecast": forecast,
        "evaluation": {
            "start": str(candidate.delivery_day.min().date()),
            "end": str(candidate.delivery_day.max().date()),
            "status": "development",
            "metrics": json.loads(table.to_json(orient="records")),
            "examples": examples,
        },
        "holdout_status": "evaluated" if final.exists() else "sealed",
        "final_evaluation": json.loads(final.read_text()) if final.exists() else None,
        "live_scorecard": json.loads(live.read_text()) if live.exists() else None,
        "decision_study": json.loads(decision.read_text())
        if decision.exists()
        else None,
    }


def write(output: Path = OUTPUT) -> Path:
    content = json.dumps(build(), indent=2, allow_nan=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(content)
    temporary.replace(output)
    return output


if __name__ == "__main__":
    print(write())
