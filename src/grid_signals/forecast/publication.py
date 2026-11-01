"""Forecast identity and delivery timing, independent of model fitting.

An information cutoff is not evidence of publication at that instant. Only the
first on-time forecast for a product/cutoff enters the operational scorecard.
"""

import fcntl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pandas as pd

DEADLINE_SLACK = timedelta(minutes=30)
PRODUCT_KEY = ["zone", "fuel_type", "resolution", "issue_time"]


def now() -> datetime:
    return datetime.now(UTC)


def status(cutoff: datetime, started: datetime, published: datetime) -> str:
    if started.date() != cutoff.date():
        return "retrospective"
    if started < cutoff:
        return "early"
    return "on_time" if published <= cutoff + DEADLINE_SLACK else "late"


def legacy_metadata(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep old rows readable without inventing publication evidence."""
    if frame.empty:
        return frame
    frame = frame.copy()
    if "issue_time" not in frame:
        frame["issue_time"] = pd.NaT
    if "forecast_id" not in frame:
        frame["forecast_id"] = None
    missing = frame.forecast_id.isna()
    frame.loc[missing, "forecast_id"] = frame.loc[missing].apply(
        lambda row: str(
            uuid5(
                NAMESPACE_URL,
                f"grid-signals:{row.zone}:{row.fuel_type}:{row.resolution}:{row.created_at}",
            )
        ),
        axis=1,
    )
    defaults = {
        "information_cutoff_at": frame.issue_time,
        "run_started_at": pd.NaT,
        "published_at": pd.NaT,
        "publication_deadline_at": pd.NaT,
        "publication_status": "legacy_unverified",
        "is_primary": False,
        "revision_of": None,
    }
    for column, default in defaults.items():
        if column not in frame:
            frame[column] = default
    frame["publication_status"] = frame.publication_status.fillna("legacy_unverified")
    frame["is_primary"] = (
        frame.is_primary.astype("boolean").fillna(value=False).astype(bool)
    )
    for column in (
        "issue_time",
        "information_cutoff_at",
        "run_started_at",
        "published_at",
        "publication_deadline_at",
    ):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def append(frame: pd.DataFrame, archive: Path, started: datetime, read) -> pd.DataFrame:
    """Publish atomically and preserve the first eligible issue across retries."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        history = legacy_metadata(read())
        out = frame.copy()
        published = now()
        cutoff = pd.Timestamp(out.issue_time.iloc[0]).to_pydatetime()
        out["forecast_id"] = str(uuid4())
        out["information_cutoff_at"] = cutoff
        out["run_started_at"] = started
        out["published_at"] = published
        out["publication_deadline_at"] = cutoff + DEADLINE_SLACK
        out["publication_status"] = status(cutoff, started, published)
        prior = history
        for key in PRODUCT_KEY:
            if not prior.empty:
                prior = prior[prior[key] == out[key].iloc[0]]
        eligible = prior[prior.is_primary] if not prior.empty else prior
        out["is_primary"] = (
            eligible.empty and out.publication_status.iloc[0] == "on_time"
        )
        out["revision_of"] = None if eligible.empty else eligible.forecast_id.iloc[0]
        combined = pd.concat([history, out], ignore_index=True)
        temporary = archive.with_suffix(".tmp.parquet")
        combined.to_parquet(temporary, index=False)
        temporary.replace(archive)
    return out


def first_eligible(frame: pd.DataFrame) -> pd.DataFrame:
    """Scoring never switches to a later revision or a reconstructed forecast."""
    if frame.empty:
        return frame
    frame = legacy_metadata(frame)
    return frame[frame.is_primary & (frame.publication_status == "on_time")].copy()
