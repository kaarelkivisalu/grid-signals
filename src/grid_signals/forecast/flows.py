"""One SE3 lifecycle for manual commands and a static Prefect runner."""

import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
from prefect import flow, serve, task
from prefect.client.schemas.schedules import CronSchedule
from prefect.runtime import flow_run
from prefect.types.entrypoint import EntrypointType

from grid_signals.forecast import journal, live, publication, saved_models, versions
from grid_signals.forecast.features import sites
from grid_signals.forecast.sources import (
    capture,
    ifs_runs,
    meps,
    observations,
    openmeteo,
)
from grid_signals.forecast.targets import labels


def event(operation: str, issue_day: date, status: str, **extra) -> None:
    journal.record(
        "lifecycle",
        {
            "operation": operation,
            "issue_day": issue_day.isoformat(),
            "status": status,
            "at": live.utcnow().isoformat(),
            "recorded_at_ns": time.time_ns(),
            **extra,
        },
        live.ROOT,
    )


def safe_action(operation: str, issue_day: date, action):
    event(operation, issue_day, "running")
    started = time.monotonic()
    try:
        result = action()
    except Exception as exc:  # noqa: BLE001 -- never persist credential-bearing provider URLs
        event(
            operation,
            issue_day,
            "failed",
            error_type=type(exc).__name__,
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
        raise RuntimeError(
            f"{operation} failed ({type(exc).__name__}); see job record"
        ) from None
    event(
        operation,
        issue_day,
        "completed",
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
    return result


@task(
    name="Fetch SE3 actuals",
    retries=2,
    retry_delay_seconds=20,
    timeout_seconds=300,
    persist_result=False,
)
def fetch_actuals(issue_day: date) -> None:
    def fetch():
        observations.refresh(
            issue_day - timedelta(days=7), issue_day + timedelta(days=1)
        )
        labels.write("SE3", "wind_onshore")

    safe_action("actuals", issue_day, fetch)


@task(
    name="Fetch SE3 weather",
    retries=1,
    retry_delay_seconds=20,
    timeout_seconds=600,
    persist_result=False,
)
def fetch_weather(issue_day: date, *, history: bool = False) -> None:
    def fetch():
        points = sites.build("SE3")
        delivery = issue_day + timedelta(days=1)
        start, end = (
            (issue_day - timedelta(days=10), issue_day)
            if history
            else (issue_day, delivery)
        )
        safe_action(
            "weather_meps",
            issue_day,
            lambda: meps.pull(points, start, end, newest_first=True),
        )
        safe_action(
            "weather_ifs", issue_day, lambda: ifs_runs.pull(points, start, end, 0)
        )
        safe_action(
            "weather_previous_runs",
            issue_day,
            lambda: openmeteo.pull(
                points, start, delivery + timedelta(days=2), merge=True
            ),
        )

    safe_action("weather", issue_day, fetch)


@task(
    name="Prepare and promote SE3 model",
    timeout_seconds=1800,
    retries=0,
    persist_result=False,
)
def prepare_model(issue_day: date) -> dict:
    def prepare():
        record = saved_models.prepare(issue_day)
        saved_models.promote(
            record["model_id"],
            issue_day,
            reason="Daily SE3 preparation; checksums and fixed-input reload comparison passed",
        )
        return {
            "model_id": record["model_id"],
            "training_max_day": record["training_max_day"],
        }

    return safe_action("prepare", issue_day, prepare)


@task(
    name="Predict SE3 from promoted model",
    timeout_seconds=180,
    retries=0,
    persist_result=False,
)
def predict_issue(issue_day: date) -> dict:
    return safe_action("prediction", issue_day, lambda: live.candidate(issue_day))


@task(
    name="Publish complete result generation",
    timeout_seconds=120,
    retries=2,
    retry_delay_seconds=5,
    persist_result=False,
)
def publish_results(issue_day: date, forecast_id: str | None = None) -> dict:
    def publish():
        pointer = live.publish(forecast_id)
        if forecast_id is not None and forecast_id not in live.current()["deliveries"]:
            raise RuntimeError("result generation was not delivered")
        return {
            "generation": pointer["generation"],
            "receipt": dict(pointer["deliveries"][forecast_id], forecast_id=forecast_id)
            if forecast_id
            else None,
        }

    return safe_action("delivery", issue_day, publish)


@task(
    name="Save public SE3 wind forecast",
    timeout_seconds=120,
    retries=1,
    retry_delay_seconds=10,
    persist_result=False,
)
def capture_public(issue_day: date) -> dict:
    def collect():
        result = capture.run("SE3", "wind_solar", issue_day + timedelta(days=1))
        if result["status"] != "captured" or not result["eligible_at_cutoff"]:
            raise RuntimeError(
                "public forecast missing, failed or received after the cutoff"
            )
        from grid_signals.forecast import windows

        grid = pd.DatetimeIndex(
            windows.delivery_day_starts(
                issue_day + timedelta(days=1), resolution=timedelta(minutes=15)
            )
        )
        if live.captured_curve(result, grid) is None:
            raise ValueError("captured public response lacks a complete SE3 wind curve")
        return {"capture_id": result["capture_id"], "eligible_at_cutoff": True}

    return safe_action("capture", issue_day, collect)


def requested_day(issue_day: date | None) -> date:
    if issue_day is not None:
        return issue_day
    # Old scheduled runs keep their original day after a runner restart.
    scheduled = flow_run.scheduled_start_time
    return scheduled.astimezone(UTC).date() if scheduled else live.utcnow().date()


@flow(
    name="SE3 wind lifecycle",
    timeout_seconds=3000,
    retries=0,
    log_prints=False,
    persist_result=False,
)
def lifecycle(
    operation: str,
    issue_day: date | None = None,
    *,
    refresh: bool = True,
    allow_late: bool = False,
) -> dict:
    if operation not in {"prepare", "capture", "forecast", "score", "status", "backup"}:
        raise ValueError("unknown forecast lifecycle operation")
    issue_day = requested_day(issue_day)
    with live.lock():
        if not (live.ROOT / "trial.json").exists():
            now = live.utcnow()
            first = (
                now.date()
                if now <= windows_cutoff(now.date()) + publication.DEADLINE_SLACK
                else now.date() + timedelta(days=1)
            )
            live.initialize(first)
        event(operation, issue_day, "running")
        try:
            safe_action("code", issue_day, versions.verify)
            result = execute(
                operation, issue_day, refresh=refresh, allow_late=allow_late
            )
        except Exception as exc:  # noqa: BLE001 -- record failure even if a Prefect task retries or times out
            event(operation, issue_day, "failed", error_type=type(exc).__name__)
            try:
                publish_results(issue_day)
            except Exception as delivery_exc:  # noqa: BLE001 -- do not turn delivery failure into flow success
                event(
                    "delivery",
                    issue_day,
                    "failed",
                    error_type=type(delivery_exc).__name__,
                )
            raise RuntimeError(
                f"SE3 {operation} failed ({type(exc).__name__}); public results may be stale"
            ) from None
        event(operation, issue_day, "completed")
        return result


def windows_cutoff(issue_day: date) -> datetime:
    from grid_signals.forecast import windows

    return windows.issue_time(issue_day)


def execute(
    operation: str, issue_day: date, *, refresh: bool, allow_late: bool
) -> dict:
    if not allow_late and issue_day < live.utcnow().date():
        raise ValueError(
            "overdue scheduled operation; keep its original day and report the missed issue"
        )
    if operation in {"prepare", "capture"} and live.utcnow() >= windows_cutoff(
        issue_day
    ):
        raise ValueError(
            "preparation or comparison collection is overdue for this issue"
        )
    if operation == "backup":
        from grid_signals.forecast import recovery

        directory = Path(os.environ.get("GRID_SIGNALS_BACKUP_DIR", "/backups"))
        destination = directory / f"forecast-{live.utcnow():%Y%m%dT%H%M%S}.tar.gz"
        return safe_action(
            "backup",
            issue_day,
            lambda: recovery.backup(destination, already_locked=True),
        )
    if operation == "prepare":
        if refresh:
            fetch_actuals(issue_day)
            fetch_weather(issue_day, history=True)
        result = prepare_model(issue_day)
        publish_results(issue_day)
        return result
    if operation == "capture":
        result = capture_public(issue_day)
        publish_results(issue_day)
        return result
    if operation == "forecast":
        existing = live.eligible_receipts(live.current()).get(issue_day.isoformat())
        if existing:
            return {"receipt": existing, "already_published": True}
        now = live.utcnow()
        cutoff = windows_cutoff(issue_day)
        if not allow_late and not cutoff <= now <= cutoff + publication.DEADLINE_SLACK:
            raise ValueError(
                "forecast is outside its issue window; overdue scheduled runs are not replayed with newer inputs"
            )
        if refresh:
            fetch_weather(issue_day)
        if not allow_late and live.utcnow() > cutoff + publication.DEADLINE_SLACK:
            raise TimeoutError("weather fetching used the publication window")
        prediction = predict_issue(issue_day)
        delivered = publish_results(issue_day, prediction["forecast_id"])
        if not allow_late and delivered["receipt"]["publication_status"] != "on_time":
            raise TimeoutError("forecast delivery missed its deadline")
        return delivered
    if operation == "score" and refresh:
        fetch_actuals(live.utcnow().date())
    return publish_results(issue_day)


def deployments(*, paused: bool = False):
    record = versions.verify()
    schedules = {
        "backup": "0 3 * * *",
        "prepare": "0 6 * * *",
        "capture": "55 8 * * *",
        "forecast": "0 9 * * *",
        "score": "0 15 * * *",
        "status": "*/15 * * * *",
    }
    return [
        lifecycle.to_deployment(
            name=f"se3-{name}",
            schedule=CronSchedule(cron=cron, timezone="UTC"),
            parameters={"operation": name},
            concurrency_limit=1,
            paused=paused,
            version=record["identity"],
            entrypoint_type=EntrypointType.MODULE_PATH,
        )
        for name, cron in schedules.items()
    ]


def start(*, paused: bool = False) -> None:
    # Unpaused schedules survive controlled shutdowns; guards reject overdue forecasts.
    configured = (
        os.environ.get("GRID_SIGNALS_SCHEDULES_PAUSED", "false").strip().lower()
    )
    if configured not in {"true", "false", "1", "0"}:
        raise ValueError("GRID_SIGNALS_SCHEDULES_PAUSED must be true or false")
    paused = paused or configured in {"true", "1"}
    serve(*deployments(paused=paused), pause_on_shutdown=False, limit=1, webserver=True)
