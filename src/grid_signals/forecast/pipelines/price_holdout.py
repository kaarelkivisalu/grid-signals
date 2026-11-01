"""Open the final price window once, under frozen sources and protocol."""

import fcntl
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from grid_signals.forecast import paths
from grid_signals.forecast.models import price as models
from grid_signals.forecast.pipelines import price
from grid_signals.forecast.sources import prices

RELEASE = paths.ROOT / "configs/releases/price_2026_10_15.json"
OUTPUT = paths.DATA / "holdout_price_2026_10_15"


def freeze() -> dict:
    if RELEASE.exists():
        return json.loads(RELEASE.read_text())
    files = [
        price.POLICY,
        Path(price.__file__),
        Path(models.__file__),
        Path(prices.__file__),
        Path(__file__),
    ]
    policy = yaml.safe_load(price.POLICY.read_text())
    manifest = {
        "release": "price_2026_10_15",
        "frozen_at": datetime.now(UTC).isoformat(),
        "start": policy["holdout_start"],
        "end_exclusive": policy["holdout_end_exclusive"],
        "methods": list(price.factories()),
        "decision": "Evaluate all four fixed methods once; no tuning or interval recalibration on this window.",
        "sources": {
            paths.source_name(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
    }
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with RELEASE.open("x") as handle:
        json.dump(manifest, handle, indent=2)
    return manifest


def run() -> dict:
    manifest = freeze()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    final = OUTPUT / "result.json"
    if final.exists():
        return json.loads(final.read_text())
    for name, digest in manifest["sources"].items():
        if hashlib.sha256(paths.source_path(name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"frozen price release changed: {name}")
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
        frame, table = price.evaluate(manifest["start"], manifest["end_exclusive"])
        frame.to_parquet(OUTPUT / "predictions.parquet", index=False)
        result = {
            "release": manifest["release"],
            "completed_at": datetime.now(UTC).isoformat(),
            "start": manifest["start"],
            "end_exclusive": manifest["end_exclusive"],
            "requested_days": (
                datetime.fromisoformat(manifest["end_exclusive"])
                - datetime.fromisoformat(manifest["start"])
            ).days,
            "metrics": json.loads(table.to_json(orient="records")),
        }
        final.write_text(json.dumps(result, indent=2, allow_nan=False))
        lines = [
            "# Final DE-LU price holdout",
            "",
            f"Frozen release: {manifest['release']}. Window: {manifest['start']} through {manifest['end_exclusive']} exclusive.",
            "",
            "All four fixed methods; monthly refits, seven-day embargo. No tuning after opening.",
            "",
            "| Method | Days | MAE EUR/MWh | CRPS EUR/MWh | 80% coverage |",
            "|---|---|---|---|---|",
            *[
                f"| {row['name']} | {row['days']} | {row['mae']:.2f} | {row['crps']:.2f} | {row['coverage_80']:.1%} |"
                for row in result["metrics"]
            ],
            "",
        ]
        (paths.REPORTS / "price_holdout.md").write_text("\n".join(lines))
        return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
