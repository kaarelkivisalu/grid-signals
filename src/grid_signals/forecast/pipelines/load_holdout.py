"""One final load evaluation with frozen source, candidate selection and input matrix."""

import fcntl
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from grid_signals.forecast import paths, windows
from grid_signals.forecast.evaluation import splits
from grid_signals.forecast.features import load as features
from grid_signals.forecast.models import load as models
from grid_signals.forecast.pipelines import backtest_products, load
from grid_signals.forecast.sources import entsoe, openmeteo
from grid_signals.forecast.sources import load as observations

RELEASE = paths.ROOT / "configs/releases/load_2026_10_15.json"
OUTPUT = paths.DATA / "holdout_load_2026_10_15"


def freeze() -> dict:
    if RELEASE.exists():
        return json.loads(RELEASE.read_text())
    config = load.policy()
    selection = json.loads(load.PROTOCOL.read_text())
    for name, digest in selection["sources"].items():
        if hashlib.sha256(paths.source_path(name).read_bytes()).hexdigest() != digest:
            raise RuntimeError("load selection sources changed before freeze")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    matrix = OUTPUT / "input_matrix.parquet"
    load.matrix().to_parquet(matrix, index=False)
    files = [
        load.POLICY,
        load.PROTOCOL,
        paths.CONFIGS / "solar_sites.csv",
        *[
            Path(module.__file__)
            for module in [
                load,
                models,
                features,
                observations,
                windows,
                splits,
                backtest_products,
                entsoe,
                openmeteo,
            ]
        ],
        Path(__file__),
    ]
    manifest = {
        "release": "load_2026_10_15",
        "frozen_at": datetime.now(UTC).isoformat(),
        "start": config["holdout_start"],
        "end_exclusive": config["holdout_end_exclusive"],
        "selected_model": selection["selected_model"],
        "selection_rule": selection["selection_rule"],
        "decision": "All four fixed methods; candidate chosen using development CRPS. No tuning after final evaluation.",
        "input_matrix": str(matrix.relative_to(paths.DATA)),
        "input_sha256": hashlib.sha256(matrix.read_bytes()).hexdigest(),
        "revision_assumption": selection["revision_assumption"],
        "sources": {
            paths.source_name(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
            if path != load.PROTOCOL
        },
        "selection_sha256": hashlib.sha256(load.PROTOCOL.read_bytes()).hexdigest(),
    }
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with RELEASE.open("x") as handle:
        json.dump(manifest, handle, indent=2)
    return manifest


def run() -> dict:
    manifest = freeze()
    final = OUTPUT / "result.json"
    if final.exists():
        return json.loads(final.read_text())
    for name, digest in manifest["sources"].items():
        if hashlib.sha256(paths.source_path(name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"frozen load source changed: {name}")
    if (
        hashlib.sha256(load.PROTOCOL.read_bytes()).hexdigest()
        != manifest["selection_sha256"]
    ):
        raise RuntimeError("frozen load model selection changed")
    matrix = paths.DATA / manifest["input_matrix"]
    if hashlib.sha256(matrix.read_bytes()).hexdigest() != manifest["input_sha256"]:
        raise RuntimeError("frozen load input matrix changed")
    with (OUTPUT / "evaluation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        opening = OUTPUT / "opened.json"
        if not opening.exists():
            opening.write_text(
                json.dumps(
                    {
                        "opened_at": datetime.now(UTC).isoformat(),
                        "release_sha256": hashlib.sha256(
                            RELEASE.read_bytes()
                        ).hexdigest(),
                    },
                    indent=2,
                )
            )
        frame, table = load.evaluate(
            manifest["start"], manifest["end_exclusive"], pd.read_parquet(matrix)
        )
        frame.to_parquet(OUTPUT / "predictions.parquet", index=False)
        expected = pd.date_range(
            manifest["start"], manifest["end_exclusive"], inclusive="left"
        )
        missing = expected.difference(pd.DatetimeIndex(frame.delivery_day.unique()))
        result = {
            "release": manifest["release"],
            "completed_at": datetime.now(UTC).isoformat(),
            "selected_model": manifest["selected_model"],
            "start": manifest["start"],
            "end_exclusive": manifest["end_exclusive"],
            "requested_days": len(expected),
            "excluded_days": [day.date().isoformat() for day in missing],
            "input_sha256": manifest["input_sha256"],
            "metrics": json.loads(table.to_json(orient="records")),
        }
        final.write_text(json.dumps(result, indent=2, allow_nan=False))
        lines = [
            "# Final DE-LU load evaluation",
            "",
            f"Release {manifest['release']}; {manifest['start']} through {manifest['end_exclusive']} exclusive. Development-selected candidate: **{manifest['selected_model']}**.",
            "",
            "Frozen input matrix and fixed source/configuration hashes. Monthly refits, seven-day embargo. No tuning after final evaluation. Historical actual-lag revisions remain an explicit assumption.",
            "",
            "| Method | Days / requested | MAE MW | CRPS MW | 80% coverage | Relative MAE |",
            "|---|---|---|---|---|---|",
            *[
                f"| {row['name']} | {row['days']} / {row['requested_days']} | {row['mae_mw']:.1f} | {row['crps_mw']:.1f} | {row['coverage_80']:.1%} | {row['relative_mae']:.3f} |"
                for row in result["metrics"]
            ],
            "",
            "Excluded complete delivery days: "
            + (", ".join(result["excluded_days"]) if len(missing) else "none")
            + ".",
            "",
        ]
        (paths.REPORTS / "load_holdout.md").write_text("\n".join(lines))
        return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
