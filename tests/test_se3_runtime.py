"""Saved-model reloads, public delivery and first-issue scoring survive failures."""

import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from grid_signals.app import explorer_data, results
from grid_signals.forecast import config, journal, live, recovery, saved_models, windows
from grid_signals.forecast.models.quantile import QuantileGBM

ISSUE = date(2026, 11, 2)


@pytest.fixture(name="runtime")
def runtime_fixture(tmp_path, monkeypatch):
    root, public, models = (
        tmp_path / "data/runtime",
        tmp_path / "public",
        tmp_path / "data/models",
    )
    monkeypatch.setattr(live, "ROOT", root)
    monkeypatch.setattr(live, "PUBLIC", public)
    monkeypatch.setattr(saved_models, "ROOT", models)
    clock = {"now": datetime(2026, 11, 2, 6, tzinfo=UTC)}
    monkeypatch.setattr(saved_models, "utcnow", lambda: clock["now"])
    monkeypatch.setattr(live, "utcnow", lambda: clock["now"])
    rng = np.random.default_rng(12)
    days = pd.date_range(pd.Timestamp(ISSUE) - pd.Timedelta(days=90), periods=90)
    training = pd.DataFrame(
        {
            "delivery_day": np.repeat(days, 24),
            "lead_hour": np.tile(np.arange(24) + 22, 90),
            "power_curve_model_mean": rng.uniform(0.05, 0.8, 90 * 24),
        }
    )
    training["cf"] = (
        training.power_curve_model_mean * 0.8 + rng.normal(0, 0.03, len(training))
    ).clip(0, 1)
    cfg = config.load()
    cfg.features["run_addressed"] = []
    cfg.model["quantile"] = {
        "calibration": "recent",
        "params": {"n_estimators": 5, "n_jobs": 1, "random_state": 42},
    }
    record = saved_models.prepare(ISSUE, training=training, cfg=cfg)
    saved_models.promote(
        record["model_id"], ISSUE, reason="test fixture reload verified"
    )
    times = pd.DatetimeIndex(windows.delivery_day_starts(ISSUE + timedelta(days=1)))
    future = pd.DataFrame(
        {
            "valid_time": times,
            "lead_hour": np.arange(len(times)) + 22,
            "capacity_mw": 1000.0,
            "power_curve_model_mean": 0.4,
        }
    )
    future["delivery_day"] = pd.Timestamp(ISSUE + timedelta(days=1))
    monkeypatch.setattr(
        live.assemble, "build_operational", lambda *_args, **_kwargs: future.copy()
    )
    source_times = pd.DataFrame(
        {"source": [pd.Timestamp(windows.issue_time(ISSUE))] * len(future)}
    )
    monkeypatch.setattr(
        live.assemble, "max_source_time", lambda _frame: source_times.copy()
    )
    clock["now"] = datetime(2026, 11, 2, 9, 5, tzinfo=UTC)
    live.initialize(ISSUE)
    empty_actuals = pd.DataFrame(columns=["period_start", "mw", "fuel_type"])
    monkeypatch.setattr(live.entsoe, "load", lambda *_args, **_kwargs: pd.DataFrame())
    return {
        "root": root,
        "public": public,
        "models": models,
        "record": record,
        "clock": clock,
        "training": training,
        "cfg": cfg,
        "source_times": source_times,
        "empty_actuals": empty_actuals,
    }


def issue(_runtime):
    value = live.candidate(ISSUE)
    frame = live.read_issue(value["forecast_id"])
    return value, frame


def observed(frame):
    return pd.DataFrame(
        {
            "period_start": frame.valid_time,
            "mw": frame["mw_q0.50"],
            "fuel_type": "wind_onshore",
        }
    )


def test_prediction_reloads_promoted_models_without_fitting(runtime, monkeypatch):
    def forbid(*_args, **_kwargs):
        pytest.fail("prediction fitted a model")

    monkeypatch.setattr(QuantileGBM, "fit", forbid)
    candidate, frame = issue(runtime)
    assert len(frame) == 96
    assert frame.saved_model_id.eq(frame.saved_model_id.iloc[0]).all()
    assert frame.saved_model_id.iloc[0] == runtime["record"]["model_id"]
    assert frame.training_max_day.iloc[0] < ISSUE.isoformat()
    assert live.current()["deliveries"] == {}
    assert candidate["forecast_id"] == frame.forecast_id.iloc[0]


def test_model_corruption_and_wrong_issue_are_rejected(runtime):
    with pytest.raises(ValueError, match="requested issue"):
        saved_models.load(ISSUE + timedelta(days=1))
    model = runtime["models"] / runtime["record"]["model_id"] / "model.pkl"
    model.write_bytes(model.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        saved_models.load(ISSUE)


def test_stale_model_is_rejected_even_if_pointer_exists(runtime):
    runtime["clock"]["now"] += timedelta(days=2)
    with pytest.raises(ValueError, match="stale"):
        saved_models.load(ISSUE)


def test_public_commit_is_idempotent_and_preserves_first_eligible_issue(runtime):
    first, frame = issue(runtime)
    pointer = live.publish(first["forecast_id"], observed=observed(frame))
    committed = (runtime["public"] / "current.json").read_bytes()
    assert live.publish(first["forecast_id"]) == pointer
    assert (runtime["public"] / "current.json").read_bytes() == committed
    runtime["clock"]["now"] += timedelta(minutes=2)
    second, _ = issue(runtime)
    newer = live.publish(second["forecast_id"], observed=observed(frame))
    selected = live.eligible_receipts(newer)[ISSUE.isoformat()]
    assert selected["forecast_id"] == first["forecast_id"]
    card = live.status_record(newer, observed=observed(frame))
    assert card["issues"][0]["forecast_id"] == first["forecast_id"]
    assert card["issues"][0]["score"]["model"]["nmae"] == 0
    assert card["issues"][0]["score"]["physical_reference"]["crps"] >= 0


def test_failed_delivery_does_not_score_and_keeps_last_working_generation(
    runtime, monkeypatch
):
    old = live.publish(observed=runtime["empty_actuals"])
    candidate, frame = issue(runtime)
    original = live.atomic_json

    def fail(path, value):
        if path.name == "current.json":
            message = "injected delivery failure"
            raise OSError(message)
        return original(path, value)

    monkeypatch.setattr(live, "atomic_json", fail)
    with pytest.raises(OSError, match="delivery failure"):
        live.publish(candidate["forecast_id"], observed=observed(frame))
    assert live.current() == old
    card = live.status_record(
        old, observed=observed(frame), now=datetime(2026, 11, 2, 10, tzinfo=UTC)
    )
    assert card["issues"][0]["status"] == "missing"
    assert card["issues"][0]["score"] is None
    monkeypatch.setattr(live, "atomic_json", original)
    published = live.publish(candidate["forecast_id"], observed=observed(frame))
    assert candidate["forecast_id"] in published["deliveries"]


def test_partial_actuals_do_not_create_forward_scores(runtime):
    candidate, frame = issue(runtime)
    pointer = live.publish(candidate["forecast_id"], observed=observed(frame).iloc[:-1])
    card = live.status_record(pointer, observed=observed(frame).iloc[:-1])
    assert card["issues"][0]["status"] == "on_time"
    assert card["issues"][0]["score"] is None
    assert live.score(frame, observed(frame))["scored_intervals"] == 96


def test_inputs_after_cutoff_are_rejected(runtime):
    runtime["source_times"].iloc[0, 0] += pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="information cutoff"):
        live.candidate(ISSUE)


def test_web_reads_checked_generation_and_retains_days_missing_during_outage(
    runtime, monkeypatch
):
    candidate, frame = issue(runtime)
    pointer = live.publish(candidate["forecast_id"], observed=observed(frame))
    monkeypatch.setenv("GRID_SIGNALS_RESULT_ROOT", str(runtime["public"]))
    manifest = explorer_data.load_manifest()
    exported = explorer_data.read_market(manifest, "SE3", "forecast")
    live_rows = exported[exported.forecast_id == candidate["forecast_id"]]
    assert len(live_rows) == 192  # model and independently fitted physical reference
    assert set(live_rows.publication_status) == {"on_time"}
    root, selected, error = results.selected()
    assert selected == pointer
    assert error is None
    card = results.publication_record(
        root, pointer, now=datetime(2026, 11, 4, 10, tzinfo=UTC)
    )
    assert [row["status"] for row in card["issues"]][-2:] == ["missing", "missing"]
    assert card["snapshot_stale"]
    assert card["reliability_gate"]["consecutive_on_time"] == 0


def test_corrupt_public_pointer_falls_back_to_previous_generation(runtime, monkeypatch):
    previous = live.publish(observed=runtime["empty_actuals"])
    candidate, frame = issue(runtime)
    live.publish(candidate["forecast_id"], observed=observed(frame))
    (runtime["public"] / "current.json").write_text("broken")
    monkeypatch.setenv("GRID_SIGNALS_RESULT_ROOT", str(runtime["public"]))
    _, pointer, error = results.selected()
    assert pointer == previous
    assert error is not None


def test_model_record_cannot_be_replaced_after_promotion(runtime):
    path = runtime["models"] / runtime["record"]["model_id"] / "record.json"
    value = json.loads(path.read_text())
    value["training_max_day"] = ISSUE.isoformat()
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="version record changed"):
        saved_models.load(ISSUE)


def test_saved_predictions_equal_the_original_fixed_input_fit(
    runtime, monkeypatch, tmp_path
):
    from grid_signals.forecast import versions
    from grid_signals.forecast.pipelines import predict

    monkeypatch.setattr(
        versions, "verify", lambda: {"identity": "original-fit-fixture"}
    )
    monkeypatch.setattr(config, "load", lambda *_args: runtime["cfg"])
    monkeypatch.setattr(
        predict.assemble, "build", lambda *_args, **_kwargs: runtime["training"].copy()
    )
    monkeypatch.setattr(predict, "VINTAGES", tmp_path / "original.parquet")
    original = predict._fit_forecast(ISSUE + timedelta(days=1), refresh=False)  # noqa: SLF001 -- direct migration comparison
    _, reloaded = issue(runtime)
    columns = [f"cf_q{level:.2f}" for level in runtime["cfg"].task.quantiles]
    np.testing.assert_allclose(
        original[columns], reloaded[columns], rtol=1e-12, atol=1e-12
    )


@pytest.mark.parametrize(
    ("delivery", "count"), [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100)]
)
def test_complete_actual_scoring_keeps_dst_delivery_days(delivery, count):
    grid = pd.DatetimeIndex(
        windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
    )
    frame = pd.DataFrame(
        {
            "valid_time": grid,
            "delivery_day": pd.Timestamp(delivery),
            "capacity_mw": 1000.0,
        }
    )
    for level in np.round(np.arange(0.05, 1, 0.05), 2):
        frame[f"cf_q{level:.2f}"] = 0.3
        frame[f"reference_cf_q{level:.2f}"] = 0.2
    frame["mw_q0.50"], frame["reference_mw_q0.50"] = 300.0, 200.0
    actuals = pd.DataFrame({"period_start": grid, "mw": 300.0})
    assert live.score(frame, actuals)["scored_intervals"] == count
    assert live.score(frame, actuals.iloc[:-1]) is None


def test_export_crossing_deadline_is_late_in_browser_and_not_score_eligible(
    runtime, monkeypatch
):
    value, frame = issue(runtime)
    runtime["clock"]["now"] = datetime(2026, 11, 2, 9, 29, 59, tzinfo=UTC)
    original = live.public_rows

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime["clock"]["now"] += timedelta(seconds=3)
        return result

    monkeypatch.setattr(live, "public_rows", delayed)
    pointer = live.publish(value["forecast_id"], observed=observed(frame))
    assert pointer["deliveries"][value["forecast_id"]]["publication_status"] == "late"
    assert live.eligible_receipts(pointer) == {}
    monkeypatch.setenv("GRID_SIGNALS_RESULT_ROOT", str(runtime["public"]))
    manifest = explorer_data.load_manifest()
    rows = explorer_data.read_market(manifest, "SE3", "forecast")
    assert set(rows[rows.forecast_id == value["forecast_id"]].publication_status) == {
        "late"
    }
    assert manifest["_publication"]["issues"][0]["score"] is None


def test_checked_backup_restore_includes_reloadable_model_and_public_receipts(
    runtime, tmp_path, monkeypatch
):
    import sqlite3

    value, frame = issue(runtime)
    pointer = live.publish(value["forecast_id"], observed=observed(frame))
    pointer = live.publish(observed=observed(frame))
    database = tmp_path / "prefect.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE evidence (value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('preserved')")
    monkeypatch.setattr(recovery.paths, "MLRUNS", tmp_path / "no-tracking")
    archive = tmp_path / "backup.tar.gz"
    backup = recovery.backup(
        archive, data=tmp_path / "data", public=runtime["public"], prefect_db=database
    )
    assert backup["prefect_database_included"]
    destination = tmp_path / "restored"
    assert recovery.restore(archive, destination)["verified_files"] > 10
    assert live.current(destination / "public") == pointer
    models, record = saved_models.load(ISSUE, root=destination / "data/models")
    probe = pd.read_parquet(
        destination / "data/models" / record["model_id"] / "reload_inputs.parquet"
    )
    expected = np.load(
        destination / "data/models" / record["model_id"] / "reload_predictions.npz"
    )
    np.testing.assert_allclose(models["model"].predict(probe), expected["model"])
    with sqlite3.connect(destination / "prefect.db") as connection:
        assert (
            connection.execute("SELECT value FROM evidence").fetchone()[0]
            == "preserved"
        )
    with pytest.raises(FileExistsError):
        recovery.restore(archive, destination)


def test_overdue_scheduled_forecast_does_not_fetch_new_inputs(runtime, monkeypatch):
    from grid_signals.forecast import flows

    runtime["clock"]["now"] = datetime(2026, 11, 3, 9, 5, tzinfo=UTC)

    def unexpected(*_args, **_kwargs):
        pytest.fail("overdue run fetched current inputs")

    monkeypatch.setattr(flows, "fetch_weather", unexpected)
    with pytest.raises(ValueError, match="overdue scheduled"):
        flows.execute("forecast", ISSUE, refresh=True, allow_late=False)


def test_prefect_deployments_are_versioned_utc_and_bounded(monkeypatch):
    from grid_signals.forecast import flows, versions

    monkeypatch.setattr(versions, "verify", lambda: {"identity": "verified-test-code"})
    deployments = flows.deployments(paused=True)
    assert len(deployments) == 6
    assert {deployment.parameters["operation"] for deployment in deployments} == {
        "backup",
        "prepare",
        "capture",
        "forecast",
        "score",
        "status",
    }
    for deployment in deployments:
        assert deployment.version == "verified-test-code"
        assert deployment.entrypoint == "grid_signals.forecast.flows.lifecycle"
        assert deployment.schedules[0].schedule.timezone == "UTC"
        assert deployment.paused
        assert deployment.concurrency_limit == 1


def test_interrupted_job_is_visible_after_runner_crash(runtime):
    journal.record(
        "lifecycle",
        {
            "operation": "forecast",
            "issue_day": ISSUE.isoformat(),
            "status": "running",
            "at": runtime["clock"]["now"].isoformat(),
        },
        live.ROOT,
    )
    card = live.status_record(
        live.current(),
        observed=runtime["empty_actuals"],
        now=datetime(2026, 11, 2, 11, tzinfo=UTC),
    )
    assert card["issues"][0]["status"] == "interrupted"
    assert card["issues"][0]["jobs"]["forecast"]["status"] == "interrupted"


def test_receipt_is_recorded_after_the_public_generation_is_visible(
    runtime, monkeypatch
):
    value, frame = issue(runtime)
    runtime["clock"]["now"] = datetime(2026, 11, 2, 9, 29, 59, tzinfo=UTC)
    original = live.atomic_json
    writes = []

    def delayed(path, payload):
        result = original(path, payload)
        if path.name == "current.json":
            writes.append(
                payload["deliveries"][value["forecast_id"]]["publication_status"]
            )
            if len(writes) == 1:
                runtime["clock"]["now"] += timedelta(seconds=3)
        return result

    monkeypatch.setattr(live, "atomic_json", delayed)
    pointer = live.publish(value["forecast_id"], observed=observed(frame))
    assert writes == ["pending_delivery", "late"]
    assert (
        pointer["deliveries"][value["forecast_id"]]["published_at"]
        == "2026-11-02T09:30:02+00:00"
    )
    assert live.eligible_receipts(pointer) == {}


def test_restart_after_public_commit_cannot_invent_an_earlier_receipt(
    runtime, monkeypatch
):
    value, frame = issue(runtime)
    original = live.atomic_json
    count = 0

    def fail_ack(path, payload):
        nonlocal count
        if path.name == "current.json":
            count += 1
            if count == 2:
                message = "crash before acknowledgement"
                raise OSError(message)
        return original(path, payload)

    monkeypatch.setattr(live, "atomic_json", fail_ack)
    with pytest.raises(OSError, match="acknowledgement"):
        live.publish(value["forecast_id"], observed=observed(frame))
    assert (
        live.current()["deliveries"][value["forecast_id"]]["publication_status"]
        == "pending_delivery"
    )
    assert live.eligible_receipts(live.current()) == {}
    monkeypatch.setattr(live, "atomic_json", original)
    runtime["clock"]["now"] = datetime(2026, 11, 2, 10, tzinfo=UTC)
    pointer = live.publish(value["forecast_id"])
    assert pointer["deliveries"][value["forecast_id"]]["publication_status"] == "late"


def test_public_reference_requires_complete_pre_cutoff_received_evidence(
    runtime, tmp_path, monkeypatch
):
    _, frame = issue(runtime)
    captures_root = tmp_path / "captures"
    monkeypatch.setattr(journal, "ROOT", captures_root)
    directory = captures_root / "raw_captures"
    directory.mkdir(parents=True)
    (directory / "public.xml").write_text("provider fixture")
    curve = pd.DataFrame(
        {
            "period_start": frame.valid_time,
            "fuel_type": "Wind Onshore",
            "forecast_mw": frame["mw_q0.50"],
        }
    )
    curve.to_parquet(directory / "public.parquet", index=False)
    capture = {
        "capture_id": "public",
        "zone": "SE3",
        "target": "wind_solar",
        "delivery_day": str(ISSUE + timedelta(days=1)),
        "status": "captured",
        "eligible_at_cutoff": True,
        "received_at": "2026-11-02T08:55:00+00:00",
        "sha256": saved_models.digest(directory / "public.xml"),
        "parsed_sha256": saved_models.digest(directory / "public.parquet"),
    }
    compared = live.public_comparison(frame, observed(frame), [capture])
    assert compared["mae_mw"] == 0
    assert compared["scored_intervals"] == 96
    capture["eligible_at_cutoff"] = False
    assert live.public_comparison(frame, observed(frame), [capture]) is None
    capture["eligible_at_cutoff"] = True
    curve.iloc[:-1].to_parquet(directory / "public.parquet", index=False)
    assert live.public_comparison(frame, observed(frame), [capture]) is None


@pytest.mark.usefixtures("runtime")
def test_provider_timeout_is_recorded_by_stage_without_secret_urls():
    import httpx

    from grid_signals.forecast import flows

    def fail():
        message = "https://provider/?token=private-fixture-token"
        raise httpx.ReadTimeout(message)

    with pytest.raises(RuntimeError, match="weather_meps failed") as error:
        flows.safe_action("weather_meps", ISSUE, fail)
    assert "private-fixture-token" not in str(error.value)
    records = journal.read("lifecycle", live.ROOT)
    assert any(row.get("error_type") == "ReadTimeout" for row in records)
    assert "private-fixture-token" not in json.dumps(records)
    assert any("elapsed_seconds" in row for row in records)


def test_checked_seed_refuses_to_overwrite_an_existing_producer(
    runtime, tmp_path, monkeypatch
):
    value, frame = issue(runtime)
    live.publish(value["forecast_id"], observed=observed(frame))
    monkeypatch.setattr(recovery.paths, "MLRUNS", tmp_path / "missing-tracking")
    archive = tmp_path / "seed.tar.gz"
    recovery.backup(archive, data=tmp_path / "data", public=live.PUBLIC)
    destination = tmp_path / "new-producer"
    seeded = recovery.seed(archive, destination=destination)
    assert seeded["archive_sha256"] == saved_models.digest(archive)
    assert (destination / "models/active.json").exists()
    with pytest.raises(FileExistsError, match="empty data"):
        recovery.seed(archive, destination=destination)


def test_crossfit_model_reloads_with_the_same_fixed_input_predictions(runtime):
    runtime["clock"]["now"] = datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    cfg = runtime["cfg"].model_copy(deep=True)
    cfg.model["quantile"]["calibration"] = "crossfit"
    record = saved_models.prepare(ISSUE, training=runtime["training"], cfg=cfg)
    saved_models.promote(record["model_id"], ISSUE, reason="Crossfit reload fixture")
    runtime["clock"]["now"] = datetime(2026, 11, 2, 9, 5, tzinfo=UTC)
    _, frame = issue(runtime)
    future = live.assemble.build_operational(ISSUE + timedelta(days=1))
    levels = np.asarray(cfg.task.quantiles)
    fresh = QuantileGBM(levels, **cfg.model["quantile"]).fit(runtime["training"])
    positions = pd.DatetimeIndex(future.valid_time).get_indexer(
        pd.DatetimeIndex(frame.valid_time).floor("h")
    )
    np.testing.assert_allclose(
        frame[[f"cf_q{level:.2f}" for level in levels]],
        fresh.predict(future)[positions],
        atol=1e-12,
        rtol=1e-12,
    )
