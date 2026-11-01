"""Check the runner with synthetic inputs, no network and no provider keys.

Run: docker run --rm -i --network none --entrypoint python IMAGE < tests/runner_image_check.py
"""

import importlib.util
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from grid_signals.forecast import (
    config,
    live,
    recovery,
    saved_models,
    versions,
    windows,
)
from grid_signals.forecast.models.quantile import QuantileGBM

assert os.getuid() != 0
assert not os.environ.get("ENTSOE_API_KEY")
for name in ("streamlit", "mlflow", "psycopg", "anthropic"):
    assert importlib.util.find_spec(name) is None
versions.verify()
with TemporaryDirectory(prefix="runner-check-") as directory:
    root = Path(directory)
    saved_models.ROOT = root / "data/models/se3-wind"
    live.ROOT, live.PUBLIC = root / "data/runtime/se3-wind", root / "public"
    recovery.paths.MLRUNS = root / "missing-tracking"
    issue_day = date(2030, 10, 26)
    clock = {"now": datetime(2030, 10, 26, 6, tzinfo=UTC)}
    saved_models.utcnow = lambda: clock["now"]
    live.utcnow = lambda: clock["now"]
    rng = np.random.default_rng(19)
    days = pd.date_range(pd.Timestamp(issue_day) - pd.Timedelta(days=90), periods=90)
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
    settings = config.load()
    settings.features["run_addressed"] = []
    settings.model["quantile"] = {
        "calibration": "recent",
        "params": {"n_estimators": 5, "n_jobs": 1},
    }
    prepared = saved_models.prepare(issue_day, training=training, cfg=settings)
    saved_models.promote(
        prepared["model_id"], issue_day, reason="Synthetic offline image check"
    )

    def forbid_fit(*_args, **_kwargs):
        message = "prediction unexpectedly fitted a model"
        raise AssertionError(message)

    QuantileGBM.fit = forbid_fit
    delivery = issue_day + timedelta(days=1)
    times = pd.DatetimeIndex(windows.delivery_day_starts(delivery))
    future = pd.DataFrame(
        {
            "valid_time": times,
            "delivery_day": pd.Timestamp(delivery),
            "lead_hour": np.arange(len(times)) + 22,
            "capacity_mw": 1000.0,
            "power_curve_model_mean": 0.4,
        }
    )
    live.assemble.build_operational = lambda *_args, **_kwargs: future.copy()
    live.assemble.max_source_time = lambda frame: pd.DataFrame(
        {"source": [pd.Timestamp(windows.issue_time(issue_day))] * len(frame)}
    )
    live.entsoe.load = lambda *_args, **_kwargs: pd.DataFrame()
    clock["now"] = datetime(2030, 10, 26, 9, 5, tzinfo=UTC)
    live.initialize(issue_day)
    candidate = live.candidate(issue_day)
    rows = live.read_issue(candidate["forecast_id"])
    assert len(rows) == 100
    actuals = pd.DataFrame(
        {
            "period_start": rows.valid_time,
            "mw": rows["mw_q0.50"],
            "fuel_type": "wind_onshore",
        }
    )
    pointer = live.publish(candidate["forecast_id"], observed=actuals)
    assert (
        pointer["deliveries"][candidate["forecast_id"]]["publication_status"]
        == "on_time"
    )
    assert live.publish(candidate["forecast_id"]) == pointer
    assert (
        live.status_record(pointer, observed=actuals)["issues"][0]["score"][
            "scored_intervals"
        ]
        == 100
    )
    archive = root / "backup.tar.gz"
    recovery.backup(archive, data=root / "data", public=live.PUBLIC)
    recovery.restore(archive, root / "restored")
    assert live.current(root / "restored/public") == pointer
    reloaded, record = saved_models.load(
        issue_day, root=root / "restored/data/models/se3-wind"
    )
    probe = pd.read_parquet(
        root
        / "restored/data/models/se3-wind"
        / record["model_id"]
        / "reload_inputs.parquet"
    )
    assert np.isfinite(reloaded["model"].predict(probe)).all()
print(
    "Runner checked: non-root, no web/tracking dependencies, saved-model prediction without fitting, DST, public commit, retry and checked restore"
)
