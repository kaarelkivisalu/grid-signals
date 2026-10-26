"""Downstream price inputs must come from genuinely earlier upstream fits."""

import fcntl
from unittest.mock import Mock

import pandas as pd
import pytest

from renewable_forecast.pipelines import price_load


def _upstream():
    return pd.DataFrame(
        {
            "valid_time": pd.to_datetime(["2026-05-01T00:00Z"]),
            "delivery_day": pd.to_datetime(["2026-05-01"]),
            "model_origin": pd.to_datetime(["2026-05-01"]),
            "training_max_day": pd.to_datetime(["2026-04-23"]),
            "issue_time": pd.to_datetime(["2026-04-30T09:00Z"]),
            "max_weather_information_time": pd.to_datetime(["2026-04-30T08:00Z"]),
        }
    )


@pytest.mark.parametrize(
    "violation", ["future_fit", "late_weather", "future_origin", "duplicate"]
)
def test_upstream_boundary_rejects_leaking_inputs(violation):
    rows = _upstream()
    price_load.validate_upstream(rows)
    if violation == "future_fit":
        rows["training_max_day"] = pd.Timestamp("2026-04-24")
    elif violation == "late_weather":
        rows["max_weather_information_time"] = pd.Timestamp("2026-04-30T10:00Z")
    elif violation == "future_origin":
        rows["model_origin"] = pd.Timestamp("2026-05-02")
    else:
        rows = pd.concat([rows, rows], ignore_index=True)
    with pytest.raises(ValueError, match=r"upstream|duplicate"):
        price_load.validate_upstream(rows)


def test_duplicate_experiment_worker_cannot_start(tmp_path, monkeypatch):
    monkeypatch.setattr(price_load, "ROOT", tmp_path)
    evaluate = Mock()
    monkeypatch.setattr(price_load, "evaluate", evaluate)
    with (tmp_path / "experiment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            price_load.run()
    evaluate.assert_not_called()
