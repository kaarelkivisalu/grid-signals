"""Publication timing and first-issue selection must survive retries and legacy data."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pandas as pd
import pytest

from renewable_forecast import journal, publication
from renewable_forecast.pipelines import score_live
from renewable_forecast.sources import capture

CUTOFF = datetime(2026, 1, 2, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    ("offset", "duration", "expected"),
    [(0, 5, "on_time"), (0, 31, "late"), (-5, 10, "early"), (1440, 1, "retrospective")],
)
def test_delivery_status_is_based_on_real_time(offset, duration, expected):
    started = CUTOFF + timedelta(minutes=offset)
    assert (
        publication.status(CUTOFF, started, started + timedelta(minutes=duration))
        == expected
    )


def _forecast():
    times = pd.date_range("2026-01-02T23:00Z", periods=96, freq="15min")
    frame = pd.DataFrame(
        {
            "valid_time": times,
            "zone": "SE3",
            "fuel_type": "wind_onshore",
            "resolution": "15min",
            "issue_time": CUTOFF,
            "created_at": CUTOFF,
            "capacity_mw": 1000.0,
            "daylight": True,
        }
    )
    for level in score_live.LEVELS:
        frame[f"cf_q{level:.2f}"] = 0.2
        frame[f"mw_q{level:.2f}"] = 200.0
    return frame


def test_retry_never_replaces_the_original_eligible_forecast(tmp_path, monkeypatch):
    archive = tmp_path / "archive.parquet"

    def read():
        return pd.read_parquet(archive) if archive.exists() else pd.DataFrame()

    monkeypatch.setattr(publication, "now", lambda: CUTOFF + timedelta(minutes=5))
    first = publication.append(_forecast(), archive, CUTOFF, read)
    second = publication.append(_forecast(), archive, CUTOFF, read)
    assert first.is_primary.all()
    assert not second.is_primary.any()
    assert second.revision_of.iloc[0] == first.forecast_id.iloc[0]
    assert second.forecast_id.iloc[0] != first.forecast_id.iloc[0]
    eligible = publication.first_eligible(read())
    assert eligible.forecast_id.unique().tolist() == first.forecast_id.unique().tolist()


def test_legacy_creation_time_does_not_establish_publication():
    legacy = publication.legacy_metadata(_forecast())
    assert legacy.publication_status.unique().tolist() == ["legacy_unverified"]
    assert legacy.published_at.isna().all()
    assert publication.first_eligible(legacy).empty


def test_live_scoring_rejects_partial_actual_days():
    forecast = _forecast()
    observed = pd.DataFrame({"period_start": forecast.valid_time, "mw": 200.0})
    assert score_live.score_issue(forecast, observed.iloc[:-1]) is None
    assert score_live.score_issue(forecast.iloc[:-1], observed) is None
    assert score_live.score_issue(forecast, observed)["nmae"] == pytest.approx(0)


def test_capture_failures_never_persist_credential_bearing_errors(
    tmp_path, monkeypatch
):
    secret = uuid4().hex
    monkeypatch.setenv("ENTSOE_API_KEY", secret)

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def query_wind_and_solar_forecast(self, *_args, **kwargs):
            assert kwargs["process_type"] == "A18"
            message = f"request failed: https://provider/?securityToken={secret}"
            raise RuntimeError(message)

    monkeypatch.setattr(capture, "EntsoeRawClient", Client)
    result = capture.run(
        "SE3", "wind_solar", CUTOFF.date() + timedelta(days=1), tmp_path
    )
    assert result["status"] == "failed"
    assert secret not in str(journal.read("captures", tmp_path))
