"""Forward price scorecard, using only immutable on-time first publications."""

import json
from datetime import UTC, datetime, timedelta
from operator import itemgetter
from pathlib import Path

import pandas as pd

from grid_signals.forecast import journal, publication, windows
from grid_signals.forecast.pipelines import price
from grid_signals.forecast.sources import prices


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
        pd.read_parquet(price.VINTAGES) if price.VINTAGES.exists() else pd.DataFrame()
    )
    primary = publication.first_eligible(archive)
    observed = prices.load()
    attempts = journal.read("runs", root)
    runs = []
    for issue in pd.date_range(start, now.date(), freq="D"):
        cutoff = windows.issue_time(issue.date())
        if cutoff + publication.DEADLINE_SLACK > now:
            continue
        rows = (
            primary
            if primary.empty
            else primary[primary.issue_time == cutoff].sort_values("valid_time")
        )
        entry = {
            "issue_day": issue.date().isoformat(),
            "status": "missing",
            "score": None,
        }
        if not rows.empty:
            entry.update(status="on_time", forecast_id=rows.forecast_id.iloc[0])
            actual = observed.reindex(pd.DatetimeIndex(rows.valid_time))
            expected = len(
                windows.delivery_day_starts(
                    issue.date() + timedelta(days=1), resolution=timedelta(minutes=15)
                )
            )
            if len(rows) == expected and actual.notna().all():
                entry["score"] = price.score(
                    actual.to_numpy(),
                    rows[[f"eur_mwh_q{q:.2f}" for q in price.models.LEVELS]].to_numpy(),
                )
        else:
            matching = [
                attempt
                for attempt in attempts
                if attempt.get("fuel_type") == "spot_price"
                and attempt.get("zone") == "DE_LU"
                and attempt.get("issue_day") == issue.date().isoformat()
            ]
            if matching:
                entry["status"] = max(matching, key=itemgetter("finished_at"))["status"]
        runs.append(entry)
    return {
        "generated_at": now.isoformat(),
        "trial_start": start,
        "unit": "EUR/MWh",
        "due_runs": len(runs),
        "on_time_runs": sum(row["status"] == "on_time" for row in runs),
        "scored_days": sum(row["score"] is not None for row in runs),
        "observation_status": "latest available auction prices; scores provisional",
        "runs": runs,
    }


def write(root: Path = journal.ROOT) -> dict:
    result = build(root)
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / "price_scorecard.tmp"
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False))
    temporary.replace(root / "price_scorecard.json")
    return result
