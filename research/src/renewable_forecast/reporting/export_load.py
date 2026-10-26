"""Export load results independently of research dependencies in the presentation."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from renewable_forecast import paths
from renewable_forecast.pipelines import load

OUTPUT = paths.ROOT.parent / "src/grid_signals/app/assets/load_snapshot.json"
LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def series(frame: pd.DataFrame, *, forecast: bool = False) -> dict:
    prefix = "mw_q" if forecast else "q"
    return {
        "time": [value.isoformat() for value in frame.valid_time],
        "quantiles_mw": {
            f"{q:.2f}": frame[f"{prefix}{q:.2f}"].round(3).tolist() for q in LEVELS
        },
    }


def build() -> dict:
    frame = pd.read_parquet(load.BACKTEST)
    metrics = pd.read_parquet(load.METRICS)
    protocol = json.loads(load.PROTOCOL.read_text())
    selected = protocol["selected_model"]
    candidate = frame[frame.forecaster == selected].copy()
    if (
        candidate.empty
        or (
            candidate.delivery_day >= pd.Timestamp(protocol["policy"]["holdout_start"])
        ).any()
    ):
        raise ValueError("load examples require non-empty development days only")
    candidate["error"] = (candidate.load - candidate["q0.50"]).abs()
    errors = candidate.groupby("delivery_day").error.mean().sort_values()
    examples = []
    for label, fraction in [
        ("Typical day", 0.5),
        ("Difficult day", 0.9),
        ("Largest error", 1),
    ]:
        day = errors.index[round((len(errors) - 1) * fraction)]
        rows = candidate[candidate.delivery_day == day].sort_values("valid_time")
        comparisons = {
            name: group.set_index("valid_time")
            .reindex(rows.valid_time)["q0.50"]
            .round(3)
            .tolist()
            for name, group in frame[frame.delivery_day == day].groupby("forecaster")
            if name != selected
        }
        examples.append(
            {
                "label": label,
                "delivery_date": day.date().isoformat(),
                "mae_mw": float(errors.loc[day]),
                **series(rows),
                "actual_mw": rows.load.round(3).tolist(),
                "comparisons_mw": comparisons,
            }
        )
    forecast = None
    if load.VINTAGES.exists():
        archive = pd.read_parquet(load.VINTAGES)
        rows = archive[archive.created_at == archive.created_at.max()].sort_values(
            "valid_time"
        )
        head = rows.iloc[0]
        forecast = {
            **series(rows, forecast=True),
            "delivery_date": head.delivery_day.date().isoformat(),
            "cutoff_at": head.information_cutoff_at.isoformat(),
            "created_at": head.created_at.isoformat(),
            "published_at": head.published_at.isoformat(),
            "forecast_id": head.forecast_id,
            "publication_status": head.publication_status,
            "model_version": head.model_version,
            "forecaster": head.forecaster,
        }
    final = paths.DATA / "holdout_load_2026_10_15/result.json"
    live = paths.DATA / "operational/load_scorecard.json"
    return {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "zone": "DE_LU",
        "unit": "MW",
        "target": "actual total load including losses, excluding absorbed storage energy",
        "selected_model": selected,
        "forecast": forecast,
        "evaluation": {
            "status": "development",
            "start": str(candidate.delivery_day.min().date()),
            "end": str(candidate.delivery_day.max().date()),
            "metrics": json.loads(metrics.to_json(orient="records")),
            "examples": examples,
        },
        "holdout_status": "evaluated" if final.exists() else "sealed",
        "final_evaluation": json.loads(final.read_text()) if final.exists() else None,
        "live_scorecard": json.loads(live.read_text()) if live.exists() else None,
        "protocol": protocol,
        "sources": {
            str(path.relative_to(paths.DATA)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in [load.BACKTEST, load.METRICS, load.PROTOCOL]
        },
        "limits": [
            "Historical lagged observations use latest revisions; first-publication vintages are not recoverable.",
            "Temperature uses six equal-area sites, rather than population-weighted regions.",
            "German national holidays are modelled; regional and Luxembourg-only holidays are not.",
            "A matched public-forecast comparison needs original pre-cutoff captures.",
        ],
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
