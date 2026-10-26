"""Export existing research results for the portfolio UI; never train or score models.

Examples come only from corrected development artifacts. Completed final scores
are exported separately; this module never calculates them or opens sealed targets.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from renewable_forecast import paths

DEFAULT_OUTPUT = (
    paths.ROOT.parent / "src/grid_signals/app/assets/forecast_snapshot.json"
)
LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
TASKS = (
    {
        "id": "se3_wind",
        "label": "SE3 · Onshore wind",
        "zone": "SE3",
        "region": "Central Sweden",
        "fuel": "wind_onshore",
        "timezone": "Europe/Stockholm",
        "model": "hourly_repeated",
        "method": "Hourly-trained quantile model; each hour repeated on the 15-minute grid",
        "limitations": [
            "Quarter-hour output repeats hourly distributions; native sub-hourly skill has not been established.",
            "The nominal 80% interval is too narrow in the winter development evaluation.",
            "Fleet availability, icing and capacity drift remain open sources of error.",
        ],
    },
    {
        "id": "delu_solar",
        "label": "DE-LU · Solar",
        "zone": "DE_LU",
        "region": "Germany-Luxembourg",
        "fuel": "solar",
        "timezone": "Europe/Berlin",
        "model": "solar_quantile",
        "method": "Native 15-minute solar quantiles over a physical PV model",
        "limitations": [
            "The fleet is approximated by six sites with a fixed orientation mix.",
            "Annual installed-capacity snapshots have no recoverable publication vintages.",
            "Headline metrics use daylight only; seasonal bias and fleet assumptions still need investigation.",
        ],
    },
)


def _series(frame: pd.DataFrame, *, forecast: bool = False) -> dict:
    times = pd.to_datetime(frame.valid_time, utc=True)
    prefix = "mw_q" if forecast else "q"
    return {
        "time": [value.isoformat() for value in times],
        "quantiles_mw": {
            f"{level:.2f}": (
                frame[f"{prefix}{level:.2f}"] * (1 if forecast else frame.capacity_mw)
            )
            .round(3)
            .tolist()
            for level in LEVELS
        },
    }


def _examples(backtest: pd.DataFrame, model: str) -> list[dict]:
    chosen = backtest[backtest.forecaster == model].copy()
    scored = chosen[chosen.daylight].copy()
    scored["error"] = (scored.cf - scored["q0.50"]).abs()
    errors = scored.groupby("delivery_day").error.mean().sort_values()
    if errors.empty:
        raise ValueError("no scored development days to export")
    examples = []
    for label, fraction in (
        ("Typical day", 0.5),
        ("Difficult day", 0.9),
        ("Largest error", 1),
    ):
        day = errors.index[round((len(errors) - 1) * fraction)]
        rows = chosen[chosen.delivery_day == day].sort_values("valid_time")
        comparisons = {}
        for name, group in backtest[backtest.delivery_day == day].groupby("forecaster"):
            if name == model:
                continue
            aligned = group.set_index("valid_time").reindex(rows.valid_time)
            comparisons[name] = (
                (aligned["q0.50"] * aligned.capacity_mw).round(3).tolist()
            )
        examples.append(
            {
                "label": label,
                "delivery_date": day.date().isoformat(),
                "nmae": float(errors.loc[day]),
                **_series(rows),
                "actual_mw": (rows.cf * rows.capacity_mw).round(3).tolist(),
                "comparisons_mw": comparisons,
            }
        )
    return examples


def build(data: Path = paths.DATA) -> dict:
    """Read the forecast archive and development artifacts into a portable bundle."""
    archive_path = data / "predictions/forecast_vintages.parquet"
    archive = pd.read_parquet(archive_path)
    sources = [archive_path]
    tasks = []
    for specification in TASKS:
        fuel = specification["fuel"]
        selected = archive[
            (archive.zone == specification["zone"])
            & (archive.fuel_type == fuel)
            & (archive.resolution == "15min")
        ]
        if selected.empty:
            raise ValueError(f"no quarter-hour forecast for {specification['id']}")
        selected = selected[
            selected.created_at == selected.created_at.max()
        ].sort_values("valid_time")
        metric_path = data / f"interim/products_15min_{fuel}.parquet"
        backtest_path = data / f"predictions/backtest_15min_{fuel}.parquet"
        metrics = pd.read_parquet(metric_path)
        backtest = pd.read_parquet(backtest_path)
        if (
            backtest.empty
            or (
                pd.to_datetime(backtest.delivery_day) >= pd.Timestamp("2026-03-20")
            ).any()
        ):
            raise ValueError("demo evaluation must contain development days only")
        sources.extend([metric_path, backtest_path])
        head = selected.iloc[0]
        tasks.append(
            {
                **specification,
                "forecast": {
                    **_series(selected, forecast=True),
                    "delivery_date": head.delivery_day.date().isoformat(),
                    "cutoff_at": head.issue_time.isoformat(),
                    "created_at": head.created_at.isoformat(),
                    "model_version": head.model_version,
                    "capacity_mw": float(head.capacity_mw),
                    "temporal_method": head.temporal_method,
                    "publication_status": head.get(
                        "publication_status", "legacy_unverified"
                    ),
                    "forecast_id": head.get("forecast_id"),
                    "published_at": (
                        head.published_at.isoformat()
                        if "published_at" in head and pd.notna(head.published_at)
                        else None
                    ),
                },
                "evaluation": {
                    "start": backtest.delivery_day.min().date().isoformat(),
                    "end": backtest.delivery_day.max().date().isoformat(),
                    "scope": "daylight" if fuel == "solar" else "all intervals",
                    "status": "development",
                    "metrics": json.loads(metrics.to_json(orient="records")),
                    "examples": _examples(backtest, specification["model"]),
                },
            }
        )
    operations = data / "operational/scorecard.json"
    trial = data / "operational/trial.json"
    holdout = data / "holdout_renewables_2026_10_15"
    final = holdout / "result.json"
    state = (
        "evaluated"
        if final.exists()
        else "evaluating"
        if (holdout / "opened.json").exists()
        else "sealed"
    )
    return {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "holdout_status": state,
        "final_evaluation": json.loads(final.read_text()) if final.exists() else None,
        "operations": {
            "trial": json.loads(trial.read_text()) if trial.exists() else None,
            "scorecard": json.loads(operations.read_text())
            if operations.exists()
            else None,
        },
        "benchmark_sources": yaml.safe_load(
            (paths.CONFIGS / "benchmarks.yaml").read_text()
        )["sources"],
        "sources": {
            str(source.relative_to(data)): hashlib.sha256(
                source.read_bytes()
            ).hexdigest()
            for source in sources
        },
        "tasks": tasks,
    }


def write(output: Path = DEFAULT_OUTPUT, data: Path = paths.DATA) -> Path:
    payload = json.dumps(build(data), indent=2, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    print(write(parser.parse_args().output))
