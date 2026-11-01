"""Exercise the real Prefect engine against isolated forecast fixture data."""

import pytest
from prefect.testing.utilities import prefect_test_harness

from grid_signals.forecast import flows, live, versions
from tests.test_se3_runtime import (  # noqa: F401 -- shared fixture
    ISSUE,
    runtime_fixture,
)


@pytest.fixture(scope="module")
def prefect_server():
    with prefect_test_harness():
        yield


@pytest.mark.usefixtures("prefect_server", "runtime")
def test_real_prefect_flow_delivers_and_retry_keeps_the_receipt(monkeypatch, tmp_path):
    record = tmp_path / "code.json"
    versions.register(record)
    monkeypatch.setattr(versions, "RECORD", record)
    result = flows.lifecycle("forecast", ISSUE, refresh=False)
    identity = result["receipt"]["forecast_id"]
    assert identity in live.current()["deliveries"]
    again = flows.lifecycle("forecast", ISSUE, refresh=False)
    assert again["already_published"]
    assert again["receipt"]["published_at"] == result["receipt"]["published_at"]


@pytest.mark.usefixtures("prefect_server")
def test_real_prefect_flow_fails_when_collection_returns_missing(
    runtime, monkeypatch, tmp_path
):
    from datetime import UTC, datetime

    record = tmp_path / "code.json"
    versions.register(record)
    monkeypatch.setattr(versions, "RECORD", record)
    runtime["clock"]["now"] = datetime(2026, 11, 2, 8, 55, tzinfo=UTC)
    monkeypatch.setattr(
        flows.capture, "run", lambda *_args, **_kwargs: {"status": "missing"}
    )
    monkeypatch.setattr(
        flows,
        "capture_public",
        flows.capture_public.with_options(retry_delay_seconds=0),
    )
    state = flows.lifecycle("capture", ISSUE, refresh=False, return_state=True)
    assert state.is_failed()
    assert live.current()["deliveries"] == {}
