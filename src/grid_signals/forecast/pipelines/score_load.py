"""Score only complete original on-time load issues; preserve missing/late days."""

import json
from datetime import UTC, datetime, timedelta
from operator import itemgetter
from pathlib import Path

import numpy as np
import pandas as pd

from grid_signals.forecast import journal, publication, windows
from grid_signals.forecast.pipelines import load
from grid_signals.forecast.sources import load as observations


def score_issue(rows: pd.DataFrame, observed: pd.Series) -> dict | None:
    delivery = rows.issue_time.iloc[0].date() + timedelta(days=1)
    grid = pd.DatetimeIndex(
        windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
    )
    ordered = rows.sort_values("valid_time")
    if not pd.DatetimeIndex(ordered.valid_time).equals(grid):
        return None
    actual = observed.reindex(grid)
    if actual.isna().any() or not np.isfinite(actual).all():
        return None
    scoring = pd.DataFrame(
        {
            "load": actual.to_numpy(),
            "normalisation_mw": ordered.normalisation_mw.to_numpy(),
        }
    )
    for level in load.models.LEVELS:
        scoring[f"q{level:.2f}"] = ordered[f"mw_q{level:.2f}"].to_numpy()
    return {**load.score(scoring), "intervals": len(grid)}


def build(root: Path = journal.ROOT) -> dict:
    trial = root / "trial.json"
    if not trial.exists():
        return {
            "status": "not_started",
            "runs": [],
            "due_runs": 0,
            "on_time_runs": 0,
            "scored_days": 0,
        }
    start = json.loads(trial.read_text())["first_issue_day"]
    now = datetime.now(UTC)
    archive = (
        pd.read_parquet(load.VINTAGES) if load.VINTAGES.exists() else pd.DataFrame()
    )
    primary = publication.first_eligible(archive)
    observed = observations.load()
    attempts = journal.read("runs", root)
    runs = []
    for issue in pd.date_range(start, now.date(), freq="D"):
        cutoff = windows.issue_time(issue.date())
        if cutoff + publication.DEADLINE_SLACK > now:
            continue
        rows = primary if primary.empty else primary[primary.issue_time == cutoff]
        entry = {
            "issue_day": issue.date().isoformat(),
            "status": "missing",
            "score": None,
        }
        if not rows.empty:
            entry.update(
                status="on_time",
                forecast_id=rows.forecast_id.iloc[0],
                score=score_issue(rows, observed),
            )
        else:
            matching = [
                attempt
                for attempt in attempts
                if attempt.get("fuel_type") == "total_load"
                and attempt.get("zone") == "DE_LU"
                and attempt.get("issue_day") == issue.date().isoformat()
            ]
            if matching:
                entry["status"] = max(matching, key=itemgetter("finished_at"))["status"]
        runs.append(entry)
    return {
        "generated_at": now.isoformat(),
        "trial_start": start,
        "unit": "MW",
        "due_runs": len(runs),
        "on_time_runs": sum(row["status"] == "on_time" for row in runs),
        "scored_days": sum(row["score"] is not None for row in runs),
        "observation_status": "latest-revised actual load; scores provisional",
        "runs": runs,
    }


def write(root: Path = journal.ROOT) -> dict:
    result = build(root)
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / "load_scorecard.tmp"
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False))
    temporary.replace(root / "load_scorecard.json")
    return result
