"""Scheduled tasks isolate failures and retain explicit stale-publication evidence."""

from datetime import UTC, datetime, timedelta

import pandas as pd

from renewable_forecast import journal, publication, windows
from renewable_forecast.pipelines import daily, price, score_price


def test_failed_wind_does_not_suppress_solar_or_price(monkeypatch):
    calls = []
    monkeypatch.setattr(
        journal, "record", lambda kind, row: calls.append((kind, row.copy()))
    )
    monkeypatch.setattr(daily, "publish_artifacts", list)
    success = pd.DataFrame(
        {"publication_status": ["late"], "forecast_id": ["example-id"]}
    )

    def predict(**kwargs):
        if kwargs["fuel"] == "wind_onshore":
            message = "private provider details"
            raise RuntimeError(message)
        return success

    monkeypatch.setattr(daily.predict, "run", predict)
    monkeypatch.setattr(daily.price_forward, "publish", lambda: success)
    monkeypatch.setattr(daily.load, "publish", lambda: success)
    result = daily.forecast(refresh=False)
    assert [row["status"] for row in result] == ["failed", "late", "late", "late"]
    assert len(calls) == 4
    assert "private provider details" not in str(calls)


def test_export_failure_keeps_other_artifacts_updating(monkeypatch):
    completed = []
    monkeypatch.setattr(journal, "record", lambda *_args: None)

    def unavailable():
        message = "artifact unavailable"
        raise OSError(message)

    monkeypatch.setattr(daily.score_live, "write", unavailable)
    monkeypatch.setattr(daily.score_price, "write", lambda: completed.append("prices"))
    monkeypatch.setattr(daily.score_load, "write", lambda: completed.append("load"))
    monkeypatch.setattr(
        daily.export_demo, "write", lambda: completed.append("renewables")
    )
    monkeypatch.setattr(
        daily.export_price, "write", lambda: completed.append("price_snapshot")
    )
    monkeypatch.setattr(
        daily.export_load, "write", lambda: completed.append("load_snapshot")
    )
    monkeypatch.setattr(
        daily.export_explorer, "write", lambda: completed.append("market_explorer")
    )
    result = daily.publish_artifacts()
    assert result[0]["status"] == "failed"
    assert completed == [
        "prices",
        "load",
        "renewables",
        "price_snapshot",
        "load_snapshot",
        "market_explorer",
    ]


def test_price_forward_score_ignores_late_rows_and_partial_actuals(
    tmp_path, monkeypatch
):
    issue = datetime.now(UTC).date() - timedelta(days=2)
    cutoff = windows.issue_time(issue)
    times = pd.DatetimeIndex(
        windows.delivery_day_starts(
            issue + timedelta(days=1), resolution=timedelta(minutes=15)
        )
    )
    rows = pd.DataFrame(
        {
            "valid_time": times,
            "issue_time": cutoff,
            "forecast_id": "first",
            "publication_status": "on_time",
            "is_primary": True,
        }
    )
    for level in price.models.LEVELS:
        rows[f"eur_mwh_q{level:.2f}"] = 50.0
    archive = tmp_path / "prices.parquet"
    rows.to_parquet(archive)
    monkeypatch.setattr(price, "VINTAGES", archive)
    (tmp_path / "trial.json").write_text(
        '{"first_issue_day": "' + issue.isoformat() + '"}'
    )
    observed = pd.Series(50.0, index=times)
    monkeypatch.setattr(score_price.prices, "load", lambda: observed)
    result = score_price.build(tmp_path)
    assert result["scored_days"] == 1
    assert result["runs"][0]["score"]["mae"] == 0

    monkeypatch.setattr(score_price.prices, "load", lambda: observed.iloc[:-1])
    assert score_price.build(tmp_path)["scored_days"] == 0

    rows["publication_status"] = "late"
    rows["is_primary"] = False
    rows.to_parquet(archive)
    assert publication.first_eligible(rows).empty
    assert score_price.build(tmp_path)["on_time_runs"] == 0
