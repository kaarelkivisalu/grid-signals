"""DE-LU load evaluation and publication with a separate final window."""

import argparse
import hashlib
import json
import logging
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd
import scoringrules as sr
import yaml
from dotenv import load_dotenv

from renewable_forecast import paths, publication, windows
from renewable_forecast.evaluation import splits
from renewable_forecast.features import load as features
from renewable_forecast.models import load as models
from renewable_forecast.pipelines.backtest_products import complete_days
from renewable_forecast.sources import load as observations

POLICY = paths.CONFIGS / "load.yaml"
BACKTEST = paths.PREDICTIONS / "backtest_load.parquet"
METRICS = paths.INTERIM / "load_metrics.parquet"
PROTOCOL = paths.INTERIM / "load_protocol.json"
VINTAGES = paths.PREDICTIONS / "load_vintages.parquet"
logger = logging.getLogger(__name__)


def policy() -> dict:
    config = yaml.safe_load(POLICY.read_text())
    if (
        config["gbm"] != models.PARAMS
        or config["lags_hours"] != list(features.LAGS)
        or config["ridge_alpha"] != 10.0
        or config["calibration_days"] != 30
        or config["assumed_actual_latency_hours"] != 24
    ):
        raise ValueError("load implementation differs from the declared fixed protocol")
    return config


def score(rows: pd.DataFrame) -> dict:
    quantiles = rows[[f"q{level:.2f}" for level in models.LEVELS]].to_numpy()
    actual = rows.load.to_numpy()
    error = quantiles[:, 9] - actual
    return {
        "mae_mw": float(np.abs(error).mean()),
        "rmse_mw": float(np.sqrt((error**2).mean())),
        "bias_mw": float(error.mean()),
        "nmae_training_mean": float((np.abs(error) / rows.normalisation_mw).mean()),
        "crps_mw": float(sr.crps_quantile(actual, quantiles, models.LEVELS).mean()),
        "coverage_80": float(
            ((actual >= quantiles[:, 1]) & (actual <= quantiles[:, 17])).mean()
        ),
        "coverage_90": float(
            ((actual >= quantiles[:, 0]) & (actual <= quantiles[:, 18])).mean()
        ),
    }


def matrix() -> pd.DataFrame:
    frame = features.build()
    frame = complete_days(frame, ["load", "temperature", "load_lag_72", "load_lag_168"])
    if (frame.max_weather_information_time > frame.issue_time).any():
        raise ValueError("load weather exceeds the fixed information cutoff")
    return frame


def evaluate(
    start: str, stop: str, frame: pd.DataFrame | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = policy()
    frame = matrix() if frame is None else frame
    first, last = pd.Timestamp(start), pd.Timestamp(stop)
    edges = sorted({first, *pd.date_range(first, last, freq="MS"), last})
    collection = []
    for origin, fold_stop in pairwise(edges):
        train_end = origin - pd.Timedelta(days=config["embargo_days"])
        train = frame[
            (frame.delivery_day < train_end)
            & (
                frame.delivery_day
                >= train_end - pd.Timedelta(days=config["training_window_days"])
            )
        ]
        test = frame[(frame.delivery_day >= origin) & (frame.delivery_day < fold_stop)]
        if train.delivery_day.nunique() < config["minimum_training_days"] or test.empty:
            raise RuntimeError(f"insufficient complete load data for {origin.date()}")
        logger.info(
            "load %s: %sd training, %sd test",
            origin.date(),
            train.delivery_day.nunique(),
            test.delivery_day.nunique(),
        )
        for name, factory in models.factories().items():
            quantiles = factory().fit(train).predict(test)
            if not np.isfinite(quantiles).all():
                raise RuntimeError(f"non-finite load forecasts: {name}")
            rows = test[["valid_time", "delivery_day", "load"]].copy()
            rows["normalisation_mw"] = float(train.load.mean())
            rows["forecaster"] = name
            for level, values in zip(models.LEVELS, quantiles.T, strict=True):
                rows[f"q{level:.2f}"] = values
            collection.append(rows)
    out = pd.concat(collection, ignore_index=True)
    columns = [f"q{level:.2f}" for level in models.LEVELS]
    naive = out[out.forecaster == "load_weekly"].sort_values("valid_time")
    reference = sr.crps_quantile(
        naive.load.to_numpy(), naive[columns].to_numpy(), models.LEVELS
    )
    records = []
    requested = (last - first).days
    for name, group in out.groupby("forecaster"):
        rows = group.sort_values("valid_time")
        if rows.valid_time.tolist() != naive.valid_time.tolist():
            raise RuntimeError("load comparison does not use identical intervals")
        loss = sr.crps_quantile(
            rows.load.to_numpy(), rows[columns].to_numpy(), models.LEVELS
        )
        low, high = splits.bootstrap_ci(pd.Series(loss - reference), rows.delivery_day)
        records.append(
            {
                "name": name,
                "days": rows.delivery_day.nunique(),
                "requested_days": requested,
                "intervals": len(rows),
                **score(rows),
                "crps_delta_low": low,
                "crps_delta_high": high,
            }
        )
    table = pd.DataFrame(records).sort_values(["crps_mw", "mae_mw"])
    table["relative_mae"] = table.mae_mw / float(
        table.loc[table.name == "load_weekly", "mae_mw"].iloc[0]
    )
    return out, table


def backtest() -> pd.DataFrame:
    config = policy()
    if pd.Timestamp(config["development_end_exclusive"]) > pd.Timestamp(
        config["holdout_start"]
    ):
        raise ValueError("load development cannot enter the final window")
    frame, table = evaluate(
        config["development_start"], config["development_end_exclusive"]
    )
    BACKTEST.parent.mkdir(parents=True, exist_ok=True)
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(BACKTEST, index=False)
    table.to_parquet(METRICS, index=False)
    metadata = {
        "created_at": datetime.now(UTC).isoformat(),
        "policy": config,
        "selected_model": table.iloc[0]["name"],
        "selection_rule": "lowest development CRPS, then MAE; fixed before final evaluation",
        "revision_assumption": "historical lag values are latest-revised observations with assumed 24-hour latency",
        "sources": {
            str(path.relative_to(paths.ROOT)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in [
                POLICY,
                Path(models.__file__),
                Path(features.__file__),
                Path(observations.__file__),
            ]
        },
    }
    PROTOCOL.write_text(json.dumps(metadata, indent=2))
    lines = [
        "# DE-LU load development benchmark",
        "",
        f"Window: {config['development_start']} through {config['development_end_exclusive']} exclusive. Selected by development CRPS: **{metadata['selected_model']}**.",
        "",
        "Monthly refits, seven-day embargo. Historical observations use latest revisions; their original vintages are not verified. See load_protocol.md.",
        "",
        "| Method | Days / requested | MAE MW | CRPS MW | 80% coverage | Relative MAE |",
        "|---|---|---|---|---|---|",
        *[
            f"| {row['name']} | {row['days']} / {row['requested_days']} | {row['mae_mw']:.1f} | {row['crps_mw']:.1f} | {row['coverage_80']:.1%} | {row['relative_mae']:.3f} |"
            for row in table.to_dict("records")
        ],
        "",
    ]
    (paths.REPORTS / "load_benchmark.md").write_text("\n".join(lines))
    return table


def publish(delivery: date | None = None) -> pd.DataFrame:
    config = policy()
    started = publication.now()
    delivery = delivery or (started.date() + timedelta(days=1))
    issue = delivery - timedelta(days=1)
    train_end = pd.Timestamp(issue) - pd.Timedelta(days=1)
    frame = matrix()
    train = frame[
        (frame.delivery_day < train_end)
        & (
            frame.delivery_day
            >= train_end - pd.Timedelta(days=config["training_window_days"])
        )
    ]
    if train.delivery_day.nunique() < config["minimum_training_days"]:
        raise RuntimeError(
            "load publication lacks sufficient complete training history"
        )
    future = features.build(
        times=pd.DatetimeIndex(
            windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
        )
    )
    if future[["temperature", "load_lag_72", "load_lag_168"]].isna().any().any():
        raise RuntimeError("load publication lacks complete eligible inputs")
    metadata = json.loads(PROTOCOL.read_text())
    if any(
        hashlib.sha256((paths.ROOT / name).read_bytes()).hexdigest() != digest
        for name, digest in metadata["sources"].items()
    ):
        raise RuntimeError("load candidate sources changed since development selection")
    chosen = metadata["selected_model"]
    quantiles = models.factories()[chosen]().fit(train).predict(future)
    if not np.isfinite(quantiles).all():
        raise RuntimeError("load publication contains non-finite forecasts")
    out = future[["valid_time", "delivery_day", "issue_time"]].copy()
    out["period_end"] = out.valid_time + pd.Timedelta(minutes=15)
    out["zone"], out["fuel_type"], out["resolution"] = "DE_LU", "total_load", "15min"
    out["forecaster"] = chosen
    out["created_at"] = datetime.now(UTC)
    fingerprint = "".join(metadata["sources"].values()).encode()
    out["model_version"] = "load-v1+" + hashlib.sha256(fingerprint).hexdigest()[:12]
    out["normalisation_mw"] = float(train.load.mean())
    for level, values in zip(models.LEVELS, quantiles.T, strict=True):
        out[f"mw_q{level:.2f}"] = values
    return publication.append(
        out,
        VINTAGES,
        started,
        lambda: pd.read_parquet(VINTAGES) if VINTAGES.exists() else pd.DataFrame(),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backtest", "predict"])
    args = parser.parse_args()
    load_dotenv(paths.ROOT.parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.action == "backtest":
        print(backtest().to_string(index=False))
    else:
        result = publish()
        print(
            json.dumps(
                {
                    "forecast_id": result.forecast_id.iloc[0],
                    "status": result.publication_status.iloc[0],
                    "intervals": len(result),
                }
            )
        )
