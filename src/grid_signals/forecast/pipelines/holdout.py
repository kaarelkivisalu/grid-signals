"""One frozen, resumable final evaluation; results are never used to retune this release."""

import argparse
import fcntl
import hashlib
import json
import logging
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

from grid_signals.forecast import config, paths
from grid_signals.forecast.evaluation import baselines, metrics
from grid_signals.forecast.evaluation.solar import SmartPersistence, SolarPhysical
from grid_signals.forecast.features import assemble, solar
from grid_signals.forecast.models.quantile import QuantileGBM
from grid_signals.forecast.models.solar import SolarQuantileGBM
from grid_signals.forecast.pipelines.backtest_products import complete_days

RELEASE = paths.ROOT / "configs/releases/renewables_2026_10_15.json"
AMENDMENT = paths.ROOT / "configs/releases/renewables_2026_10_15_amendment_1.json"
OUTPUT = paths.DATA / "holdout_renewables_2026_10_15"
START, END = pd.Timestamp("2026-03-20"), pd.Timestamp("2026-09-20")
logger = logging.getLogger(__name__)


def freeze() -> dict:
    if RELEASE.exists():
        return json.loads(RELEASE.read_text())
    sources = [
        *paths.CONFIGS.glob("*.yaml"),
        *paths.CONFIGS.glob("*.csv"),
        *paths.CONFIGS.glob("*.geojson"),
        *paths.CONFIGS.glob("experiments/*.yaml"),
        *paths.PACKAGE.glob("features/*.py"),
        *paths.PACKAGE.glob("models/*.py"),
        *paths.PACKAGE.glob("targets/*.py"),
        *paths.PACKAGE.glob("sources/*.py"),
        Path(__file__),
    ]
    manifest = {
        "release": "renewables_2026_10_15",
        "frozen_at": datetime.now(UTC).isoformat(),
        "holdout_start": str(START.date()),
        "holdout_end_exclusive": str(END.date()),
        "refit": "2026-03-20 then first of each month; train days strictly before origin minus seven days",
        "wind": "hourly-trained quantile GBM repeated to genuine quarter-hour targets; physical reference on same rows",
        "solar": "native quarter-hour quantile GBM; physical and smart-persistence references on same daylight rows",
        "n_jobs": 4,
        "decision": "No selection, calibration changes or tuning after results are opened.",
        "sources": {
            paths.source_name(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(sources))
        },
        "config": {
            name: config.load("delu_solar" if name == "solar" else None).model_dump(
                mode="json"
            )
            for name in ["wind", "solar"]
        },
    }
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with RELEASE.open("x") as handle:
        json.dump(manifest, handle, indent=2)
    return manifest


def verify(manifest: dict) -> None:
    expected = manifest["sources"].copy()
    if AMENDMENT.exists():
        amendment = json.loads(AMENDMENT.read_text())
        for name, change in amendment["sources"].items():
            if expected[name] != change["original_sha256"]:
                raise RuntimeError("amendment does not match the frozen release")
            expected[name] = change["amended_sha256"]
    changed = [
        name
        for name, digest in expected.items()
        if hashlib.sha256(paths.source_path(name).read_bytes()).hexdigest() != digest
    ]
    if changed:
        raise RuntimeError(f"frozen candidate source changed: {changed}")


def run_task(fuel: str, manifest: dict) -> pd.DataFrame:
    cfg = config.Config.model_validate(
        manifest["config"]["solar" if fuel == "solar" else "wind"]
    )
    levels = np.array(cfg.task.quantiles)
    kwargs = cfg.model.get("quantile", {}).copy()
    kwargs["params"] = {**kwargs.get("params", {}), "n_jobs": manifest["n_jobs"]}
    is_solar = fuel == "solar"
    flags = assemble.run_flags(cfg.features.get("run_addressed", ()))
    if is_solar:
        required = ["cf", "physical_cf", "clear_sky_cf"]
        training = complete_days(solar.build(), required)
        future = training
    else:
        training = assemble.require_run_coverage(
            assemble.build(**flags), cfg.features.get("run_addressed", ())
        )
        future = assemble.build(resolution="15min", **flags)
        required = ["cf", "power_curve_model_mean", *assemble.RUN_SOURCES.values()]
    future = complete_days(
        future[(future.delivery_day >= START) & (future.delivery_day < END)], required
    )
    edges = [START, *pd.date_range("2026-04-01", "2026-09-01", freq="MS"), END]
    parts = []
    for origin, stop in pairwise(edges):
        checkpoint = OUTPUT / f"{fuel}_{origin.date()}.parquet"
        if checkpoint.exists():
            parts.append(pd.read_parquet(checkpoint))
            continue
        verify(manifest)
        train = training[training.delivery_day < origin - pd.Timedelta(days=7)]
        test = future[(future.delivery_day >= origin) & (future.delivery_day < stop)]
        if test.empty or train.delivery_day.nunique() < 180:
            raise RuntimeError(f"insufficient data for {fuel} {origin.date()}")
        logger.info(
            "%s %s: fitting %sd; forecasting %sd",
            fuel,
            origin.date(),
            train.delivery_day.nunique(),
            test.delivery_day.nunique(),
        )
        factory = SolarQuantileGBM if is_solar else QuantileGBM
        model = factory(levels, **kwargs).fit(train)
        if is_solar:
            predictions = {"quantile": model.predict(test)}
            for reference in [
                SolarPhysical(levels),
                SmartPersistence(levels, training),
            ]:
                predictions[reference.name] = reference.fit(train).predict(test)
        else:
            hourly = training[training.delivery_day.isin(test.delivery_day.unique())]
            predictions = {}
            for name, fitted in [
                ("quantile", model),
                (
                    "physical_power_curve",
                    baselines.PhysicalPowerCurve(levels).fit(train),
                ),
            ]:
                values = pd.DataFrame(fitted.predict(hourly), index=hourly.valid_time)
                predictions[name] = values.reindex(
                    test.valid_time.dt.floor("h")
                ).to_numpy()
        frames = []
        for name, quantiles in predictions.items():
            if not np.isfinite(quantiles).all():
                raise RuntimeError("incomplete holdout forecast")
            out = test[["valid_time", "delivery_day", "cf", "capacity_mw"]].copy()
            out["daylight"] = test.solar_elevation > 5 if is_solar else True
            out["forecaster"] = name
            for level, values in zip(levels, quantiles.T, strict=True):
                out[f"q{level:.2f}"] = values
            frames.append(out)
        combined = pd.concat(frames, ignore_index=True)
        temporary = checkpoint.with_suffix(".tmp.parquet")
        combined.to_parquet(temporary, index=False)
        temporary.replace(checkpoint)
        parts.append(combined)
    return pd.concat(parts, ignore_index=True)


def run() -> dict:
    manifest = freeze()
    verify(manifest)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    final = OUTPUT / "result.json"
    if final.exists():
        return json.loads(final.read_text())
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
        tables = {}
        for fuel in ["wind_onshore", "solar"]:
            frame = run_task(fuel, manifest)
            rows = []
            for name, context in frame.groupby("forecaster"):
                scored = context[context.daylight]
                summary = metrics.summarise(
                    scored.cf.to_numpy(),
                    scored[
                        [f"q{q:.2f}" for q in np.arange(0.05, 1, 0.05).round(2)]
                    ].to_numpy(),
                    np.arange(0.05, 1, 0.05).round(2),
                )
                rows.append(
                    {
                        "name": name,
                        "days": context.delivery_day.nunique(),
                        "scored_intervals": len(scored),
                        "requested_days": 184,
                        **summary,
                    }
                )
            tables[fuel] = rows
        result = {
            "release": manifest["release"],
            "completed_at": datetime.now(UTC).isoformat(),
            "evaluation": tables,
            "amendment": json.loads(AMENDMENT.read_text())
            if AMENDMENT.exists()
            else None,
        }
        final.write_text(json.dumps(result, indent=2, allow_nan=False))
        lines = [
            "# Final renewable holdout",
            "",
            "Frozen release: renewables_2026_10_15. Delivery 2026-03-20 to 2026-09-19.",
            "",
            "Monthly rolling refits with a seven-day embargo. No retuning after this evaluation.",
            "",
        ]
        for fuel, rows in tables.items():
            lines += [
                f"## {fuel}",
                "",
                "| Model | Days / 184 | nMAE | CRPS | 80% coverage |",
                "|---|---|---|---|---|",
            ]
            lines += [
                f"| {row['name']} | {row['days']} | {row['nmae']:.2%} | {row['crps']:.5f} | {row['coverage_80']:.1%} |"
                for row in rows
            ]
            lines += [""]
        (paths.REPORTS / "holdout.md").write_text("\n".join(lines) + "\n")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print(json.dumps(freeze() if args.freeze_only else run(), indent=2))
