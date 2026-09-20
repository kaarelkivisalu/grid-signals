"""MLflow wiring.

Headline scalars go to MLflow so runs can be compared in the UI; the full metric grid
(metric x lead hour x season x ...) goes as a parquet artifact, because MLflow metrics
are scalar-keyed and a grid does not fit that shape without becoming unreadable.
"""

import contextlib
import json
import logging
import subprocess  # noqa: S404 - only used to read local git state
import tempfile
from collections.abc import Iterator
from pathlib import Path

import mlflow
import pandas as pd

from renewable_forecast import paths
from renewable_forecast.config import Config

logger = logging.getLogger(__name__)

EXPERIMENT = "se3-vre-forecast"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=paths.ROOT,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _git_dirty() -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=paths.ROOT,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return bool(out.strip())


def configure() -> None:
    """Point MLflow at a local SQLite backend inside the project.

    Still serverless -- one file, no daemon -- but the filesystem store is in
    maintenance mode upstream, and SQLite is queryable directly when the UI is
    overkill.
    """
    paths.MLRUNS.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{paths.MLRUNS / 'mlflow.db'}")
    if mlflow.get_experiment_by_name(EXPERIMENT) is None:
        mlflow.create_experiment(
            EXPERIMENT, artifact_location=(paths.MLRUNS / "artifacts").as_uri()
        )
    mlflow.set_experiment(EXPERIMENT)


@contextlib.contextmanager
def run(name: str, config: Config | None = None, **tags) -> Iterator[None]:
    """Open an MLflow run tagged with the config fingerprint and git state."""
    configure()
    with mlflow.start_run(run_name=name):
        mlflow.set_tags({"git_sha": _git_sha(), "git_dirty": _git_dirty(), **tags})
        if config is not None:
            mlflow.set_tag("config_fingerprint", config.fingerprint())
            mlflow.log_params(
                {
                    "zone": config.task.zone,
                    "fuel_types": ",".join(config.task.fuel_types),
                    "resolution": config.task.resolution,
                    "issue_hour_utc": config.task.issue_hour_utc,
                    "n_quantiles": len(config.task.quantiles),
                    "embargo_days": config.splits.embargo_days,
                    "holdout_months": config.splits.holdout_months,
                }
            )
        yield


def log_metrics(scalars: dict[str, float]) -> None:
    """Log the headline numbers."""
    mlflow.log_metrics({k: float(v) for k, v in scalars.items() if pd.notna(v)})


def log_table(frame: pd.DataFrame, name: str) -> None:
    """Attach a DataFrame to the run as a parquet artifact.

    This is where the metric *grid* lives. MLflow metrics are scalar-keyed, so
    per-lead-hour and per-season breakdowns would be unreadable as flat metric names.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        mlflow.log_artifact(str(path))


def log_json(payload: dict, name: str) -> None:
    """Attach a small JSON document to the run."""
    mlflow.log_text(json.dumps(payload, indent=2, default=str), f"{name}.json")


def leaderboard() -> pd.DataFrame:
    """Every run's headline metrics, best CRPS first."""
    configure()
    runs = mlflow.search_runs(experiment_names=[EXPERIMENT])
    if runs.empty:
        return runs
    cols = ["tags.mlflow.runName", "metrics.crps", "metrics.nmae", "metrics.nrmse"]
    keep = [c for c in cols if c in runs.columns]
    out = runs[keep].rename(columns=lambda c: c.split(".")[-1])
    return out.sort_values("crps") if "crps" in out.columns else out
