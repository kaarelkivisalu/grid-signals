"""A web release contains only the current, checked results and forecast UI."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.prepare_demo import checked_results, prepare

ROOT = Path(__file__).parents[1]


def test_release_copies_only_indexed_results_and_product_pages(tmp_path):
    output = tmp_path / "release"
    report = prepare(ROOT, output)
    app = output / "src/grid_signals/app"
    index = json.loads((app / "assets/explorer/manifest.json").read_text())
    expected = {
        info[key]
        for info in index["zones"].values()
        for key in ("forecast_file", "observation_file")
        if info[key]
    }
    assert {
        path.name for path in (app / "assets/explorer").glob("*.parquet")
    } == expected
    assert report["result_files"] == len(expected)
    assert {path.name for path in (app / "pages").iterdir()} == {
        "overview.py",
        "wind.py",
        "solar.py",
        "price.py",
        "load.py",
        "performance.py",
        "coverage.py",
        "methods.py",
    }
    assert {path.name for path in (output / "src/grid_signals").iterdir()} == {
        "__init__.py",
        "app",
    }
    assert not (output / ".env").exists()
    with pytest.raises(FileExistsError):
        prepare(ROOT, output)


@pytest.mark.parametrize("problem", ["missing", "corrupt", "unsafe_path", "wrong_name"])
def test_release_rejects_broken_result_index(tmp_path, problem):
    raw = b"saved result fixture"
    digest = hashlib.sha256(raw).hexdigest()[:16]
    name = f"SE3-forecasts-{digest}.parquet"
    (tmp_path / name).write_bytes(raw)
    if problem == "missing":
        (tmp_path / name).unlink()
    elif problem == "corrupt":
        (tmp_path / name).write_bytes(b"damaged result")
    elif problem == "unsafe_path":
        name = f"../{name}"
    else:
        wrong = f"DE_LU-forecasts-{digest}.parquet"
        (tmp_path / name).rename(tmp_path / wrong)
        name = wrong
    index = {
        "schema_version": 1,
        "zones": {"SE3": {"forecast_file": name, "observation_file": None}},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(index))
    with pytest.raises((ValueError, FileNotFoundError)):
        checked_results(tmp_path)
