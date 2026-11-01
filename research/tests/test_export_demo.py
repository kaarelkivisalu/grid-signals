"""The presentation exporter cannot silently expose holdout evaluation results."""

import json

import pandas as pd
import pytest

from grid_signals.app.snapshot import DEFAULT_SNAPSHOT
from grid_signals.forecast.reporting import export_demo


def test_export_rejects_holdout_evaluation_rows(monkeypatch, tmp_path):
    forecast = pd.DataFrame(
        {
            "zone": ["SE3"],
            "fuel_type": ["wind_onshore"],
            "resolution": ["15min"],
            "created_at": [pd.Timestamp("2026-10-15", tz="UTC")],
            "valid_time": [pd.Timestamp("2026-10-15", tz="UTC")],
        }
    )

    def read(path):
        if path.name == "forecast_vintages.parquet":
            return forecast
        if path.name.startswith("products_"):
            return pd.DataFrame()
        return pd.DataFrame({"delivery_day": [pd.Timestamp("2026-03-20")]})

    monkeypatch.setattr(pd, "read_parquet", read)
    with pytest.raises(ValueError, match="development days only"):
        export_demo.build(tmp_path)


def test_snapshot_contains_only_declared_development_examples():
    snapshot = json.loads(DEFAULT_SNAPSHOT.read_text())
    for task in snapshot["tasks"]:
        assert task["evaluation"]["status"] == "development"
        assert task["evaluation"]["end"] < "2026-03-20"
        assert all(
            example["delivery_date"] < "2026-03-20"
            for example in task["evaluation"]["examples"]
        )
        assert task["forecast"]["publication_status"] in {
            "research_preview",
            "legacy_unverified",
            "early",
            "late",
            "retrospective",
            "on_time",
        }
