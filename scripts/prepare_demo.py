"""Check saved results and copy only the forecast website into a release directory.

Uses the standard library so the image build needs no forecasting dependencies.
Older exports and original research files are left untouched.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

APP_FILES = (
    "__init__.py",
    "main.py",
    "explorer_data.py",
    "explorer_charts.py",
    "model_catalogue.py",
    "presentation.py",
    "snapshot.py",
    "results.py",
    "publication.py",
    "pages/overview.py",
    "pages/wind.py",
    "pages/solar.py",
    "pages/price.py",
    "pages/load.py",
    "pages/performance.py",
    "pages/map.py",
    "pages/methods.py",
    "assets/forecast_snapshot.json",
    "assets/price_snapshot.json",
    "assets/load_snapshot.json",
    "assets/explorer/manifest.json",
    "assets/explorer/market-areas.geojson",
)


def checked_results(root: Path) -> list[Path]:
    """Reject missing, renamed or damaged files before assembling the release."""
    index = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if index["schema_version"] != 1 or not index["zones"]:
        message = "The explorer file index is empty or incompatible."
        raise ValueError(message)
    files = []
    for zone, info in index["zones"].items():
        for kind in ("forecast", "observation"):
            name = info[f"{kind}_file"]
            if name is None:
                continue
            if Path(name).name != name or not name.endswith(".parquet"):
                message = f"Invalid result filename: {name}"
                raise ValueError(message)
            path = root / name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            if name != f"{zone}-{kind}s-{digest}.parquet":
                message = f"Result checksum or name does not match: {name}"
                raise ValueError(message)
            files.append(path)
    return files


def prepare(source: Path, output: Path) -> dict:
    """Make a new self-contained directory; never modify the source results."""
    app = Path("src/grid_signals/app")
    results = checked_results(source / app / "assets/explorer")
    files = [
        Path("src/grid_signals/__init__.py"),
        Path("src/grid_signals/markets.py"),
        Path(".streamlit/config.toml"),
        *(app / name for name in APP_FILES),
        *(path.relative_to(source) for path in results),
    ]
    # Check the whole file set before writing anything.
    for file in files:
        if not (source / file).is_file():
            raise FileNotFoundError(source / file)
    output.mkdir(parents=True, exist_ok=False)
    for file in files:
        destination = output / file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / file, destination)
    return {"result_files": len(results), "files": len(files)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.source.resolve(), args.output.resolve()))
