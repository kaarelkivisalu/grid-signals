"""Operational scorecard: eligible first issues, complete actuals and missing runs."""

import json
from datetime import UTC, date, datetime, timedelta
from operator import itemgetter
from pathlib import Path

import numpy as np
import pandas as pd

from grid_signals.forecast import journal, publication, windows
from grid_signals.forecast.evaluation import metrics
from grid_signals.forecast.pipelines import predict
from grid_signals.forecast.sources import entsoe
from grid_signals.forecast.targets import actuals

TASKS = (("SE3", "wind_onshore"), ("DE_LU", "solar"))
LEVELS = np.array([round(i * 0.05, 2) for i in range(1, 20)])


def score_issue(forecast: pd.DataFrame, observed: pd.DataFrame) -> dict | None:
    """A partial delivery day remains unscored; no easy-hour survivorship."""
    delivery = forecast.issue_time.iloc[0].date() + timedelta(days=1)
    expected = pd.DatetimeIndex(
        windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
    )
    if not pd.DatetimeIndex(forecast.valid_time).sort_values().equals(expected):
        return None
    merged = forecast.merge(
        observed[["period_start", "mw"]],
        left_on="valid_time",
        right_on="period_start",
        how="left",
        validate="one_to_one",
    )
    if merged.mw.isna().any() or not np.isfinite(merged.mw).all():
        return None
    rows = merged[merged.daylight] if "daylight" in merged else merged
    if rows.empty:
        return None
    return {
        **metrics.summarise(
            (rows.mw / rows.capacity_mw).to_numpy(),
            rows[[f"cf_q{level:.2f}" for level in LEVELS]].to_numpy(),
            LEVELS,
        ),
        "mae_mw": float((rows.mw - rows["mw_q0.50"]).abs().mean()),
        "scored_intervals": len(rows),
    }


def build(start: date, end: date, root: Path = journal.ROOT) -> dict:
    """Report every due product/issue, including days with no successful run."""
    archive = predict._read_vintages()  # noqa: SLF001
    primary = publication.first_eligible(archive)
    attempts = journal.read("runs", root)
    results = []
    now = datetime.now(UTC)
    for zone, fuel in TASKS:
        raw = entsoe.load("actual_generation", zone)
        observed = (
            actuals.to_quarter_hourly(raw)
            if not raw.empty
            else pd.DataFrame(columns=["zone", "fuel_type", "period_start", "mw"])
        )
        observed = observed[observed.fuel_type == fuel]
        for issue in pd.date_range(start, end, inclusive="left"):
            cutoff = windows.issue_time(issue.date())
            if cutoff + publication.DEADLINE_SLACK > now:
                continue
            rows = primary
            if not rows.empty:
                rows = rows[
                    (rows.zone == zone)
                    & (rows.fuel_type == fuel)
                    & (rows.resolution == "15min")
                    & (rows.issue_time == cutoff)
                ]
            entry = {
                "zone": zone,
                "fuel_type": fuel,
                "issue_day": issue.date().isoformat(),
                "status": "missing",
                "score": None,
            }
            if not rows.empty:
                entry.update(status="on_time", forecast_id=rows.forecast_id.iloc[0])
                entry["score"] = score_issue(rows, observed)
            else:
                matching = [
                    attempt
                    for attempt in attempts
                    if attempt.get("zone") == zone
                    and attempt.get("fuel_type") == fuel
                    and attempt.get("issue_day") == issue.date().isoformat()
                ]
                if matching:
                    latest = max(matching, key=itemgetter("finished_at"))
                    entry["status"] = latest["status"]
            results.append(entry)
    return {
        "generated_at": now.isoformat(),
        "trial_start": start.isoformat(),
        "due_runs": len(results),
        "on_time_runs": sum(row["status"] == "on_time" for row in results),
        "scored_days": sum(row["score"] is not None for row in results),
        "observation_status": "latest available actuals; scores remain provisional",
        "runs": results,
    }


def write(root: Path = journal.ROOT) -> dict:
    trial = root / "trial.json"
    if not trial.exists():
        return {
            "status": "not_started",
            "runs": [],
            "due_runs": 0,
            "on_time_runs": 0,
            "scored_days": 0,
        }
    start = date.fromisoformat(json.loads(trial.read_text())["first_issue_day"])
    result = build(start, datetime.now(UTC).date() + timedelta(days=1), root)
    temporary = root / "scorecard.tmp"
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False))
    temporary.replace(root / "scorecard.json")
    return result


if __name__ == "__main__":
    print(json.dumps(write(), indent=2))
