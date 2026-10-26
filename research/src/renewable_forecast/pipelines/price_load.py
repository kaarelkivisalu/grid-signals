"""Development ablation: fixed price GBM with out-of-sample custom load inputs."""

import fcntl
import hashlib
import json
import logging
from datetime import UTC, datetime
from itertools import pairwise
from operator import itemgetter
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import scoringrules as sr
import yaml

from renewable_forecast import paths
from renewable_forecast.evaluation import splits
from renewable_forecast.models import load as load_models
from renewable_forecast.models import price as price_models
from renewable_forecast.pipelines import load_holdout, price
from renewable_forecast.sources import prices

POLICY = paths.CONFIGS / "price_load.yaml"
ROOT = paths.DATA / "price_load_v1"
SUMMARY = paths.INTERIM / "price_load_metrics.json"
logger = logging.getLogger(__name__)
MODES = ("price_only", "custom_load_point", "custom_load_quantiles")


def prepare() -> dict:
    config = yaml.safe_load(POLICY.read_text())
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = ROOT / "experiment.json"
    if manifest.exists():
        recorded = json.loads(manifest.read_text())
        for name, digest in recorded["sources"].items():
            if hashlib.sha256((paths.ROOT / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"price/load experiment source changed: {name}")
        return config
    files = [
        POLICY,
        Path(__file__),
        Path(price_models.__file__),
        Path(load_models.__file__),
        Path(prices.__file__),
    ]
    recorded = {
        "declared_at": datetime.now(UTC).isoformat(),
        "policy": config,
        "load_release": json.loads(load_holdout.RELEASE.read_text()),
        "sources": {
            str(path.relative_to(paths.ROOT)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in files
        },
    }
    manifest.write_text(json.dumps(recorded, indent=2))
    return config


def validate_upstream(frame: pd.DataFrame) -> None:
    if frame.valid_time.duplicated().any():
        raise ValueError("duplicate upstream forecast intervals")
    if not (frame.training_max_day < frame.model_origin - pd.Timedelta(days=7)).all():
        raise ValueError("upstream load fit crosses its training embargo")
    if not (frame.model_origin <= frame.delivery_day).all():
        raise ValueError("upstream model originates after delivery")
    if not (frame.max_weather_information_time <= frame.issue_time).all():
        raise ValueError("upstream weather postdates information cutoff")


def upstream(config: dict) -> pd.DataFrame:
    release = json.loads(load_holdout.RELEASE.read_text())
    source = paths.DATA / release["input_matrix"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != release["input_sha256"]:
        raise ValueError("frozen load matrix changed")
    for name, digest in release["sources"].items():
        if hashlib.sha256((paths.ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"frozen upstream source changed: {name}")
    frame = pd.read_parquet(source)
    first, last = (
        pd.Timestamp(config["upstream_start"]),
        pd.Timestamp(config["upstream_end_exclusive"]),
    )
    edges = sorted({first, *pd.date_range(first, last, freq="MS"), last})
    parts = []
    for origin, stop in pairwise(edges):
        checkpoint = ROOT / f"load_inputs_{origin.date()}.parquet"
        if checkpoint.exists():
            parts.append(pd.read_parquet(checkpoint))
            continue
        train_end = origin - pd.Timedelta(days=7)
        train = frame[
            (frame.delivery_day < train_end)
            & (frame.delivery_day >= train_end - pd.Timedelta(days=730))
        ]
        test = frame[(frame.delivery_day >= origin) & (frame.delivery_day < stop)]
        if train.delivery_day.nunique() < 180 or test.empty:
            raise ValueError(
                f"insufficient out-of-sample load history for {origin.date()}"
            )
        logger.info(
            "upstream load %s: %sd training, %sd prediction",
            origin.date(),
            train.delivery_day.nunique(),
            test.delivery_day.nunique(),
        )
        values = load_models.QuantileLoad().fit(train).predict(test)
        rows = test[
            ["valid_time", "delivery_day", "issue_time", "max_weather_information_time"]
        ].copy()
        rows["model_origin"], rows["training_max_day"] = (
            origin,
            train.delivery_day.max(),
        )
        for level in [0.10, 0.50, 0.90]:
            position = int(np.argmin(np.abs(load_models.LEVELS - level)))
            rows[f"load_q{level:.2f}_gw"] = values[:, position] / 1000
        validate_upstream(rows)
        temporary = checkpoint.with_suffix(".tmp.parquet")
        rows.to_parquet(temporary, index=False)
        temporary.replace(checkpoint)
        parts.append(rows)
    result = pd.concat(parts, ignore_index=True)
    validate_upstream(result)
    return result


class PriceWithLoad:
    def __init__(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError("unknown price input mode")
        self.mode = mode

    def fit(self, frame: pd.DataFrame):
        self.columns = [
            column
            for column in frame
            if column.startswith(("p_lag_", "profile_", "dow_"))
            or column in {"quarter", "month"}
        ]
        if self.mode != "price_only":
            self.columns.append("load_q0.50_gw")
        if self.mode == "custom_load_quantiles":
            self.columns += ["load_q0.10_gw", "load_q0.90_gw"]
        self.models = [
            lgb.LGBMRegressor(
                objective="quantile", alpha=float(level), **price_models.PARAMS
            ).fit(frame[self.columns], frame.price)
            for level in price_models.LEVELS
        ]
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.sort(
            np.column_stack(
                [model.predict(frame[self.columns]) for model in self.models]
            ),
            axis=1,
        )


def evaluate() -> dict:
    config = prepare()
    if pd.Timestamp(config["development_end_exclusive"]) > pd.Timestamp("2026-09-01"):
        raise ValueError("price/load experiment cannot reopen the final price window")
    upstream_rows = upstream(config)
    history = prices.load()
    base = prices.features(history)
    base = base[
        base.valid_time.isin(prices.native(history).index) & base.p_lag_168.notna()
    ]
    merged = base.merge(
        upstream_rows.drop(columns=["delivery_day", "issue_time"]),
        on="valid_time",
        validate="one_to_one",
    )
    merged = price.complete_days(merged)
    origins = pd.date_range(
        config["development_start"], config["development_end_exclusive"], freq="MS"
    )
    parts = []
    for origin, stop in pairwise(origins):
        train_end = origin - pd.Timedelta(days=7)
        train = merged[
            (merged.delivery_day < train_end)
            & (merged.delivery_day >= train_end - pd.Timedelta(days=730))
        ]
        test = merged[(merged.delivery_day >= origin) & (merged.delivery_day < stop)]
        if train.delivery_day.nunique() < 180 or test.empty:
            raise ValueError("insufficient matched price/load history")
        logger.info(
            "price inputs %s: %sd common training, %sd common test",
            origin.date(),
            train.delivery_day.nunique(),
            test.delivery_day.nunique(),
        )
        for mode in MODES:
            checkpoint = ROOT / f"{mode}_{origin.date()}.parquet"
            if checkpoint.exists():
                parts.append(pd.read_parquet(checkpoint))
                continue
            values = PriceWithLoad(mode).fit(train).predict(test)
            if not np.isfinite(values).all():
                raise ValueError("non-finite price/load forecasts")
            rows = test[["valid_time", "delivery_day", "price"]].copy()
            rows["method"] = mode
            for level, column in zip(price_models.LEVELS, values.T, strict=True):
                rows[f"q{level:.2f}"] = column
            temporary = checkpoint.with_suffix(".tmp.parquet")
            rows.to_parquet(temporary, index=False)
            temporary.replace(checkpoint)
            parts.append(rows)
    frame = pd.concat(parts, ignore_index=True)
    columns = [f"q{level:.2f}" for level in price_models.LEVELS]
    reference = frame[frame.method == "price_only"].sort_values("valid_time")
    reference_loss = sr.crps_quantile(
        reference.price.to_numpy(), reference[columns].to_numpy(), price_models.LEVELS
    )
    records = []
    for name, group in frame.groupby("method"):
        rows = group.sort_values("valid_time")
        if rows.valid_time.tolist() != reference.valid_time.tolist():
            raise ValueError("price/load evaluation intervals differ")
        loss = sr.crps_quantile(
            rows.price.to_numpy(), rows[columns].to_numpy(), price_models.LEVELS
        )
        low, high = splits.bootstrap_ci(
            pd.Series(loss - reference_loss), rows.delivery_day
        )
        records.append(
            {
                "name": name,
                "days": rows.delivery_day.nunique(),
                "intervals": len(rows),
                **price.score(rows.price.to_numpy(), rows[columns].to_numpy()),
                "crps_delta_low": low,
                "crps_delta_high": high,
            }
        )
    result = {
        "experiment": config["experiment"],
        "status": "joint development experiment",
        "start": config["development_start"],
        "end_exclusive": config["development_end_exclusive"],
        "requested_days": (
            pd.Timestamp(config["development_end_exclusive"])
            - pd.Timestamp(config["development_start"])
        ).days,
        "generated_at": datetime.now(UTC).isoformat(),
        "metrics": sorted(records, key=itemgetter("crps")),
        "limitation": "Upstream configuration selected in load development; historical load revisions assumed. New forward data required for confirmation.",
        "input_sha256": hashlib.sha256(
            (
                paths.DATA
                / json.loads(load_holdout.RELEASE.read_text())["input_matrix"]
            ).read_bytes()
        ).hexdigest(),
    }
    frame.to_parquet(ROOT / "predictions.parquet", index=False)
    SUMMARY.write_text(json.dumps(result, indent=2, allow_nan=False))
    lines = [
        "# Price input experiment: custom load",
        "",
        "Joint development comparison, May-August 2026. Out-of-sample upstream predictions; identical downstream train/test rows. No independent final claim.",
        "",
        "| Inputs | Days / 123 | MAE EUR/MWh | CRPS EUR/MWh | 80% coverage | CRPS delta 95% CI |",
        "|---|---|---|---|---|---|",
        *[
            f"| {row['name']} | {row['days']} | {row['mae']:.2f} | {row['crps']:.2f} | {row['coverage_80']:.1%} | {row['crps_delta_low']:+.2f} to {row['crps_delta_high']:+.2f} |"
            for row in result["metrics"]
        ],
        "",
        result["limitation"],
        "",
    ]
    (paths.REPORTS / "price_load.md").write_text("\n".join(lines))
    return result


def run() -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "experiment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return evaluate()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print(json.dumps(run(), indent=2))
