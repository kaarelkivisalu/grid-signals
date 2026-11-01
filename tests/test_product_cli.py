"""The installed CLI works away from the checkout and dispatches shared functions."""

import json
import os
import subprocess  # noqa: S404 -- fixed interpreter and test arguments
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from grid_signals import cli
from grid_signals.forecast import paths, versions
from grid_signals.products import ENTSOE_CODES, PRODUCTS, renewable_product


def test_configured_paths_do_not_depend_on_source_checkout(tmp_path):
    data, output = tmp_path / "inputs", tmp_path / "results"
    result = subprocess.run(  # noqa: S603 -- fixed interpreter and test arguments
        [
            sys.executable,
            "-m",
            "grid_signals",
            "--data-dir",
            str(data),
            "--output-dir",
            str(output),
            "info",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(result.stdout)
    assert info["data"] == str(data)
    assert info["output"] == str(output)
    assert set(info["products"]) == set(PRODUCTS)
    assert Path(info["configs"], "base.yaml").is_file()
    assert not data.exists(), "info must not create data or invoke a provider"


@pytest.mark.parametrize(
    "command", ["fetch-actuals", "train", "backtest", "fetch-context", "fetch-era5"]
)
def test_help_never_starts_a_pipeline(command, tmp_path):
    result = subprocess.run(  # noqa: S603 -- fixed interpreter and test arguments
        [sys.executable, "-m", "grid_signals", command, "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "usage:" in result.stdout
    assert not list(tmp_path.iterdir())


def test_cli_passes_pipeline_options_in_order(monkeypatch):
    from grid_signals.forecast.pipelines import backtest_products

    action = Mock(return_value=0)
    monkeypatch.setattr(backtest_products, "main", action)
    assert cli.main(["backtest", "--fuel", "solar"]) == 0
    action.assert_called_once_with(["--fuel", "solar"])


def test_product_registry_does_not_claim_unevaluated_forecasts():
    assert ENTSOE_CODES["NO5"] == "NO_5"
    assert ENTSOE_CODES["SE3"] == "SE_3"
    assert renewable_product("SE3", "wind_onshore").fleet == "vindbrukskollen"
    with pytest.raises(ValueError, match="No evaluated"):
        renewable_product("SE4", "wind_onshore")


def test_new_code_record_is_immutable_and_rejects_changed_sources(
    tmp_path, monkeypatch
):
    candidate = {"package/models/wind.py": "first checksum"}
    record = tmp_path / "version.json"
    monkeypatch.setattr(versions, "RECORD", record)
    monkeypatch.setattr(versions, "sources", candidate.copy)
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "INTERIM", tmp_path)
    versions.register(record)
    assert versions.verify()["identity"].startswith("consolidated-v1+")
    with pytest.raises(FileExistsError):
        versions.register(record)
    candidate["package/models/wind.py"] = "changed checksum"
    with pytest.raises(RuntimeError, match="differ"):
        versions.verify()


def test_publishing_identity_does_not_import_mlflow(tmp_path):
    environment = {
        **os.environ,
        "GRID_SIGNALS_VERSION_RECORD": str(versions.RECORD.resolve()),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from grid_signals.forecast.pipelines import predict; assert 'mlflow' not in sys.modules",
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
