"""Load targets, units, data revisions and information boundaries."""

from datetime import date, timedelta
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from renewable_forecast import paths, windows
from renewable_forecast.features import load as features
from renewable_forecast.models import load as models
from renewable_forecast.pipelines import load as pipeline
from renewable_forecast.pipelines import score_load
from renewable_forecast.sources import load as source


def test_actual_targets_are_not_manufactured_from_hourly_values():
    hourly = pd.Series(
        50000.0, index=pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    )
    assert source.native(hourly).empty
    native = pd.Series(
        50000.0, index=pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    )
    assert len(source.native(native)) == 96
    assert len(source.native(native.iloc[:-1])) == 92


def test_interpolation_uses_the_latest_endpoint_to_choose_information_age():
    times = pd.DatetimeIndex(["2026-10-16T08:45Z", "2026-10-16T09:00Z"])
    issues = pd.Series(pd.to_datetime(["2026-10-15T09:00Z"] * 2))
    raw = pd.DataFrame(
        {
            "valid_time": pd.date_range("2026-10-16T08:00Z", periods=3, freq="h"),
            "point_id": "a",
            "model": features.MODEL,
            "temperature_2m_previous_day1": 10.0,
            "temperature_2m_previous_day2": 20.0,
        }
    )
    points = pd.DataFrame({"point_id": ["a"], "weight": [1.0]})
    frame = features.temperature(times, issues, raw, points)
    assert frame.temperature.tolist() == [10.0, 20.0]
    assert frame.nwp_offset_days.tolist() == [1, 2]
    assert (frame.max_weather_information_time <= issues).all()


def test_unknown_target_load_cannot_change_forecast_features():
    times = pd.DatetimeIndex(
        windows.delivery_day_starts(
            date(2026, 10, 16), resolution=timedelta(minutes=15)
        )
    )
    history_times = pd.date_range(
        times.min() - pd.Timedelta(days=10), times.max(), freq="15min"
    )
    history = pd.Series(50000.0, index=history_times)
    hours = pd.date_range(times.min().floor("h"), times.max().ceil("h"), freq="h")
    points = pd.read_csv(paths.CONFIGS / "solar_sites.csv")
    raw = pd.concat(
        [
            pd.DataFrame(
                {
                    "valid_time": hours,
                    "point_id": point,
                    "model": features.MODEL,
                    "temperature_2m_previous_day1": 10.0,
                    "temperature_2m_previous_day2": 12.0,
                }
            )
            for point in points.point_id
        ],
        ignore_index=True,
    )
    first = features.build(history, times, raw)
    changed = history.copy()
    changed.loc[times] = 999999.0
    second = features.build(changed, times, raw)
    pd.testing.assert_frame_equal(first[features.COLUMNS], second[features.COLUMNS])
    assert (second.load != first.load).all()


@pytest.mark.parametrize("delivery", [date(2026, 3, 29), date(2026, 10, 25)])
def test_load_evaluation_keeps_whole_dst_days(monkeypatch, delivery):
    times = pd.DatetimeIndex(
        windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
    )
    frame = pd.DataFrame(
        {
            "valid_time": times,
            "delivery_day": pd.Timestamp(delivery),
            "issue_time": windows.issue_time(delivery - timedelta(days=1)),
            "max_weather_information_time": windows.issue_time(
                delivery - timedelta(days=1)
            ),
            "load": 50000.0,
            "temperature": 10.0,
            "load_lag_72": 50000.0,
            "load_lag_168": 50000.0,
        }
    )
    monkeypatch.setattr(features, "build", lambda: frame)
    assert len(pipeline.matrix()) == len(times)
    frame.loc[0, "temperature"] = np.nan
    assert pipeline.matrix().empty


def test_load_forecasts_remain_in_megawatts(monkeypatch):
    monkeypatch.setattr(models, "PARAMS", {**models.PARAMS, "n_estimators": 3})
    train = pd.DataFrame(0.0, index=range(80), columns=features.COLUMNS)
    train["load"] = np.linspace(45000, 55000, len(train))
    predicted = models.QuantileLoad().fit(train).predict(train)
    assert predicted.min() > 1000
    assert np.isfinite(predicted).all()
    assert (np.diff(predicted, axis=1) >= 0).all()


def test_failed_load_requests_do_not_log_credentials(monkeypatch, caplog):
    secret = uuid4().hex

    class Client:
        def query_load(self, *_args, **_kwargs):
            message = f"https://provider/?securityToken={secret}"
            raise RuntimeError(message)

    monkeypatch.setattr(source.entsoe, "client", Client)
    result = source.pull(date(2026, 1, 1), date(2026, 1, 2))
    assert result["failed"] == 1
    assert secret not in caplog.text


def test_live_load_score_needs_a_complete_valid_dst_day():
    delivery = date(2026, 3, 29)
    times = pd.DatetimeIndex(
        windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
    )
    rows = pd.DataFrame(
        {
            "valid_time": times,
            "issue_time": windows.issue_time(delivery - timedelta(days=1)),
            "normalisation_mw": 50000.0,
        }
    )
    for level in models.LEVELS:
        rows[f"mw_q{level:.2f}"] = 50000.0
    actual = pd.Series(50000.0, index=times)
    assert score_load.score_issue(rows, actual)["mae_mw"] == 0
    assert score_load.score_issue(rows.iloc[:-1], actual) is None
    assert score_load.score_issue(rows, actual.iloc[:-1]) is None
    actual.iloc[0] = np.inf
    assert score_load.score_issue(rows, actual) is None
