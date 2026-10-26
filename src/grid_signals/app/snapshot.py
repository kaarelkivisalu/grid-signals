"""Read portable research snapshots without loading the modelling or database stack."""

import json
import math
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_SNAPSHOT = Path(__file__).parent / "assets/forecast_snapshot.json"

MODEL_LABELS = {
    "hourly_repeated": "Hourly model · repeated quarters",
    "interpolated_weather": "Hourly model · interpolated weather",
    "solar_quantile": "Solar quantile model",
    "smart_persistence": "Smart persistence · 48 hours",
    "solar_physical": "Physical PV model",
    "clear_sky_climatology": "Clear-sky climatology",
    "seasonal_naive": "Weekly seasonal naive",
    "lear_hourly": "LEAR · price-only, hourly",
    "lightgbm_point": "LightGBM · median + residuals",
    "lightgbm_quantile": "LightGBM · direct quantiles",
    "quantile": "Selected quantile model",
    "physical_power_curve": "Physical wind power curve",
    "load_weekly": "Weekly load persistence",
    "load_ridge": "Temperature / calendar ridge",
    "load_point_gbm": "Load LightGBM · median + residuals",
    "load_quantile_gbm": "Load LightGBM · direct quantiles",
}


class SnapshotError(ValueError):
    """A missing or incompatible portfolio snapshot."""


def _validate_series(series: dict) -> None:
    times = series["time"]
    parsed = [datetime.fromisoformat(value) for value in times]
    if not parsed or any(value.tzinfo is None for value in parsed):
        msg = "series must contain timezone-aware intervals"
        raise ValueError(msg)
    if parsed != sorted(set(parsed)):
        msg = "intervals must be unique and ordered"
        raise ValueError(msg)
    levels = ("0.05", "0.10", "0.25", "0.50", "0.75", "0.90", "0.95")
    suffix = "eur_mwh" if "quantiles_eur_mwh" in series else "mw"
    arrays = [series[f"quantiles_{suffix}"][level] for level in levels]
    arrays.extend([series[f"actual_{suffix}"]] if f"actual_{suffix}" in series else [])
    arrays.extend(series.get(f"comparisons_{suffix}", {}).values())
    if any(
        len(values) != len(times) or any(not math.isfinite(value) for value in values)
        for values in arrays
    ):
        msg = "interval values must be finite and aligned"
        raise ValueError(msg)
    for values in zip(
        *(series[f"quantiles_{suffix}"][level] for level in levels), strict=True
    ):
        if list(values) != sorted(values):
            msg = "forecast quantiles cross"
            raise ValueError(msg)


def _validate_snapshot(payload: dict) -> None:
    if payload["schema_version"] != 1 or not payload["tasks"]:
        msg = "unsupported or empty snapshot"
        raise ValueError(msg)
    for task in payload["tasks"]:
        for key in (
            "id",
            "label",
            "zone",
            "region",
            "fuel",
            "model",
            "method",
            "limitations",
        ):
            if not task[key]:
                msg = "incomplete task metadata"
                raise ValueError(msg)
        ZoneInfo(task["timezone"])
        forecast = task["forecast"]
        date.fromisoformat(forecast["delivery_date"])
        for key in ("cutoff_at", "created_at"):
            if datetime.fromisoformat(forecast[key]).tzinfo is None:
                msg = "forecast provenance must include timezone-aware timestamps"
                raise ValueError(msg)
        if not forecast["model_version"] or not math.isfinite(forecast["capacity_mw"]):
            msg = "incomplete forecast provenance"
            raise ValueError(msg)
        evaluation = task["evaluation"]
        date.fromisoformat(evaluation["start"])
        date.fromisoformat(evaluation["end"])
        if not evaluation["examples"]:
            msg = "no development examples"
            raise ValueError(msg)
        _validate_series(task["forecast"])
        for example in evaluation["examples"]:
            date.fromisoformat(example["delivery_date"])
            if not example["label"] or not math.isfinite(example["nmae"]):
                msg = "invalid development example"
                raise ValueError(msg)
            _validate_series(example)
        for row in evaluation["metrics"]:
            for key in (
                "nmae",
                "crps",
                "coverage_80",
                "coverage_90",
                "days",
                "scored_intervals",
            ):
                if not math.isfinite(row[key]):
                    msg = "incomplete evaluation metrics"
                    raise ValueError(msg)
        if not any(row["name"] == task["model"] for row in evaluation["metrics"]):
            msg = "task model is missing its evaluation"
            raise ValueError(msg)


def load_snapshot(path: Path | None = None) -> dict:
    """Load the bundled snapshot, or the explicit local override."""
    selected = path or Path(
        os.environ.get("GRID_SIGNALS_SNAPSHOT_PATH", DEFAULT_SNAPSHOT)
    )
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
        _validate_snapshot(payload)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = "The forecast snapshot is missing or incompatible."
        raise SnapshotError(msg) from exc
    return payload


def model_metrics(task: dict) -> dict:
    return next(
        row for row in task["evaluation"]["metrics"] if row["name"] == task["model"]
    )


def _validate_secondary_snapshot(payload: dict, unit: str) -> None:
    if payload["schema_version"] != 1 or payload["unit"] != unit:
        msg = "incompatible forecast snapshot"
        raise ValueError(msg)
    if payload["forecast"]:
        forecast = payload["forecast"]
        date.fromisoformat(forecast["delivery_date"])
        for key in ("cutoff_at", "created_at", "published_at"):
            if datetime.fromisoformat(forecast[key]).tzinfo is None:
                msg = "forecast provenance must include timezone-aware timestamps"
                raise ValueError(msg)
        if not forecast["model_version"] or not forecast["forecast_id"]:
            msg = "incomplete forecast provenance"
            raise ValueError(msg)
        _validate_series(forecast)
    for example in payload["evaluation"]["examples"]:
        _validate_series(example)


def load_price_snapshot(path: Path | None = None) -> dict | None:
    selected = path or Path(
        os.environ.get(
            "GRID_SIGNALS_PRICE_SNAPSHOT_PATH",
            Path(__file__).parent / "assets/price_snapshot.json",
        )
    )
    if not selected.exists():
        return None
    try:
        payload = json.loads(selected.read_text())
        _validate_secondary_snapshot(payload, "EUR/MWh")
    except (OSError, ValueError, KeyError, TypeError) as error:
        msg = "The price snapshot is missing or incompatible."
        raise SnapshotError(msg) from error
    return payload


def load_load_snapshot(path: Path | None = None) -> dict | None:
    selected = path or Path(
        os.environ.get(
            "GRID_SIGNALS_LOAD_SNAPSHOT_PATH",
            Path(__file__).parent / "assets/load_snapshot.json",
        )
    )
    if not selected.exists():
        return None
    try:
        payload = json.loads(selected.read_text())
        _validate_secondary_snapshot(payload, "MW")
    except (OSError, ValueError, KeyError, TypeError) as error:
        msg = "The load snapshot is missing or incompatible."
        raise SnapshotError(msg) from error
    return payload
