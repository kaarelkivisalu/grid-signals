"""The portfolio must remain useful without the operational services."""

import json

import pytest

from grid_signals.app.snapshot import (
    SnapshotError,
    load_load_snapshot,
    load_price_snapshot,
    load_snapshot,
)


@pytest.mark.parametrize("problem", ["crossing", "unaligned", "metadata", "nonfinite"])
def test_corrupt_snapshot_is_rejected_before_rendering(tmp_path, problem):
    snapshot = load_snapshot()
    task = snapshot["tasks"][0]
    quantiles = task["forecast"]["quantiles_mw"]
    if problem == "crossing":
        quantiles["0.05"][0] = quantiles["0.95"][0] + 1
    elif problem == "unaligned":
        quantiles["0.50"].pop()
    elif problem == "metadata":
        del task["region"]
    else:
        quantiles["0.50"][0] = float("nan")
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot))
    with pytest.raises(SnapshotError):
        load_snapshot(path)


@pytest.mark.parametrize("problem", ["crossing", "metadata", "nonfinite"])
def test_price_snapshot_validates_units_quantiles_and_provenance(tmp_path, problem):
    snapshot = load_price_snapshot()
    assert snapshot is not None
    forecast = snapshot["forecast"]
    if problem == "crossing":
        forecast["quantiles_eur_mwh"]["0.05"][0] = (
            forecast["quantiles_eur_mwh"]["0.95"][0] + 1
        )
    elif problem == "metadata":
        forecast["published_at"] = "2026-10-15T14:00:00"
    else:
        forecast["quantiles_eur_mwh"]["0.50"][0] = float("nan")
    path = tmp_path / "price.json"
    path.write_text(json.dumps(snapshot))
    with pytest.raises(SnapshotError):
        load_price_snapshot(path)


def test_load_bundle_rejects_incompatible_units(tmp_path):
    snapshot = load_load_snapshot()
    assert snapshot is not None
    snapshot["unit"] = "EUR/MWh"
    path = tmp_path / "load.json"
    path.write_text(json.dumps(snapshot))
    with pytest.raises(SnapshotError):
        load_load_snapshot(path)
