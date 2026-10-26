"""Price-only DE-LU benchmark, forecast archive and report; price holdout stays sealed."""

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
from renewable_forecast.models import price as models
from renewable_forecast.sources import prices

logger = logging.getLogger(__name__)
BACKTEST = paths.PREDICTIONS / "backtest_price.parquet"
METRICS = paths.INTERIM / "price_metrics.parquet"
VINTAGES = paths.PREDICTIONS / "price_vintages.parquet"
POLICY = paths.CONFIGS / "price.yaml"


def complete_days(frame: pd.DataFrame) -> pd.DataFrame:
    expected = frame.delivery_day.map(
        lambda day: len(
            windows.delivery_day_starts(day.date(), resolution=timedelta(minutes=15))
        )
    )
    complete = frame.groupby("delivery_day").valid_time.transform("nunique") == expected
    return frame[complete].copy()


def factories() -> dict:
    return {
        "seasonal_naive": models.SeasonalNaive,
        "lear_hourly": lambda: models.ResidualDistribution(models.Lear),
        "lightgbm_point": lambda: models.ResidualDistribution(models.PointGBM),
        "lightgbm_quantile": models.QuantileGBM,
    }


def score(actual: np.ndarray, quantiles: np.ndarray) -> dict:
    median = quantiles[:, 9]
    error = median - actual
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(np.mean(error)),
        "crps": float(np.mean(sr.crps_quantile(actual, quantiles, models.LEVELS))),
        "coverage_80": float(
            np.mean((actual >= quantiles[:, 1]) & (actual <= quantiles[:, 17]))
        ),
        "coverage_90": float(
            np.mean((actual >= quantiles[:, 0]) & (actual <= quantiles[:, 18]))
        ),
    }


def evaluate(start: str, stop: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the declared fixed methods to one explicit window."""
    policy = yaml.safe_load(POLICY.read_text())
    if policy["gbm"] != models.PARAMS:
        raise ValueError("price model parameters differ from the declared protocol")
    first, last = pd.Timestamp(start), pd.Timestamp(stop)
    origins = sorted({first, *pd.date_range(first, last, freq="MS"), last})
    history = prices.load()
    frame = prices.features(history)
    observed = prices.native(history)
    native = frame[frame.valid_time.isin(observed.index) & frame.p_lag_168.notna()]
    native = complete_days(native)
    collection = []
    for origin, fold_stop in pairwise(origins):
        end = origin - pd.Timedelta(days=policy["embargo_days"])
        train = frame[
            (frame.delivery_day < end)
            & (frame.delivery_day >= end - pd.Timedelta(days=730))
        ]
        native_train = native[
            (native.delivery_day < end)
            & (native.delivery_day >= end - pd.Timedelta(days=730))
        ]
        test = native[
            (native.delivery_day >= origin) & (native.delivery_day < fold_stop)
        ]
        if native_train.delivery_day.nunique() < 180 or test.empty:
            raise RuntimeError(
                f"insufficient native-quarter history for {origin.date()}"
            )
        logger.info(
            "price %s: %sd native training, %sd test",
            origin.date(),
            native_train.delivery_day.nunique(),
            test.delivery_day.nunique(),
        )
        for name, factory in factories().items():
            model = factory().fit(train if name == "lear_hourly" else native_train)
            quantiles = model.predict(test)
            if not np.isfinite(quantiles).all():
                raise RuntimeError(f"non-finite price predictions: {name}")
            rows = test[["valid_time", "delivery_day", "price"]].copy()
            rows["forecaster"] = name
            for level, values in zip(models.LEVELS, quantiles.T, strict=True):
                rows[f"q{level:.2f}"] = values
            collection.append(rows)
    out = pd.concat(collection, ignore_index=True)
    columns = [f"q{level:.2f}" for level in models.LEVELS]
    reference = out[out.forecaster == "seasonal_naive"].sort_values("valid_time")
    reference_loss = sr.crps_quantile(
        reference.price.to_numpy(), reference[columns].to_numpy(), models.LEVELS
    )
    table = []
    for name, group in out.groupby("forecaster"):
        context = group.sort_values("valid_time")
        if context.valid_time.tolist() != reference.valid_time.tolist():
            raise RuntimeError("price benchmark rows differ")
        values = context[columns].to_numpy()
        loss = sr.crps_quantile(context.price.to_numpy(), values, models.LEVELS)
        low, high = splits.bootstrap_ci(
            pd.Series(loss - reference_loss), context.delivery_day
        )
        table.append(
            {
                "name": name,
                "days": context.delivery_day.nunique(),
                "intervals": len(context),
                **score(context.price.to_numpy(), values),
                "crps_delta_low": low,
                "crps_delta_high": high,
            }
        )
    result = pd.DataFrame(table).sort_values("crps")
    naive_mae = result[result.name == "seasonal_naive"].mae.iloc[0]
    result["relative_mae"] = result.mae / naive_mae
    return out, result


def backtest() -> pd.DataFrame:
    policy = yaml.safe_load(POLICY.read_text())
    if pd.Timestamp(policy["development_end_exclusive"]) > pd.Timestamp(
        policy["holdout_start"]
    ):
        raise ValueError("price development may not enter the sealed price holdout")
    out, result = evaluate(
        policy["development_start"], policy["development_end_exclusive"]
    )
    BACKTEST.parent.mkdir(parents=True, exist_ok=True)
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(BACKTEST, index=False)
    result.to_parquet(METRICS, index=False)
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": policy,
        "policy_sha256": hashlib.sha256(POLICY.read_bytes()).hexdigest(),
        "input_mode": "price-only; historical fundamentals excluded",
        "model_source_sha256": hashlib.sha256(
            Path(models.__file__).read_bytes()
        ).hexdigest(),
    }
    (paths.INTERIM / "price_protocol.json").write_text(json.dumps(metadata, indent=2))
    write_report(result)
    return result


def publish(delivery: date | None = None) -> pd.DataFrame:
    started = publication.now()
    delivery = delivery or (started.date() + timedelta(days=1))
    issue = delivery - timedelta(days=1)
    history = prices.load()
    frame = prices.features(history)
    native = frame[frame.valid_time.isin(prices.native(history).index)]
    train = native[
        (native.delivery_day <= pd.Timestamp(issue))
        & (native.delivery_day >= pd.Timestamp(issue) - pd.Timedelta(days=730))
    ]
    if train.delivery_day.nunique() < 180:
        raise RuntimeError("price forecast needs 180 native-quarter training days")
    times = pd.DatetimeIndex(
        windows.delivery_day_starts(delivery, resolution=timedelta(minutes=15))
    )
    future = prices.features(history, times)
    if future.p_lag_168.isna().any():
        raise RuntimeError("price forecast lacks a complete known weekly price curve")
    model = models.QuantileGBM().fit(train)
    quantiles = model.predict(future)
    out = future[["valid_time", "delivery_day", "issue_time"]].copy()
    out["period_end"] = out.valid_time + pd.Timedelta(minutes=15)
    out["zone"], out["fuel_type"], out["resolution"] = "DE_LU", "spot_price", "15min"
    out["created_at"] = datetime.now(UTC)
    out["model_version"] = (
        "price-v1+"
        + hashlib.sha256(
            POLICY.read_bytes()
            + Path(models.__file__).read_bytes()
            + Path(prices.__file__).read_bytes()
        ).hexdigest()[:12]
    )
    for level, values in zip(models.LEVELS, quantiles.T, strict=True):
        out[f"eur_mwh_q{level:.2f}"] = values
    return publication.append(
        out,
        VINTAGES,
        started,
        lambda: pd.read_parquet(VINTAGES) if VINTAGES.exists() else pd.DataFrame(),
    )


def write_report(table: pd.DataFrame) -> None:
    lines = [
        "# DE-LU day-ahead price benchmark",
        "",
        "Price-only development evaluation, 2026-05-01 to 2026-08-31. The separate September to mid-October price holdout is sealed.",
        "",
        "Monthly refits; seven-day embargo; two-year training window. Native quarter-hour actual targets, including negative prices. LEAR uses hourly price profiles and repeats its hourly median; it is a price-only adaptation, not an exact reproduction of the exogenous epftoolbox benchmark.",
        "",
        "Public fundamentals are excluded because historical publication vintages have not been verified at the 09:00 UTC cutoff.",
        "",
        "| Method | Days | MAE EUR/MWh | CRPS EUR/MWh | 80% coverage | Relative MAE |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {row['name']} | {row['days']} | {row['mae']:.2f} | {row['crps']:.2f} | {row['coverage_80']:.1%} | {row['relative_mae']:.3f} |"
        for row in table.to_dict("records")
    ]
    lines += [
        "",
        "Paired day-block bootstrap CRPS differences are stored with the machine-readable metrics. No MAPE is used around zero or negative prices.",
        "",
    ]
    (paths.REPORTS / "price_benchmark.md").write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["refresh", "backtest", "predict"])
    args = parser.parse_args()
    load_dotenv(paths.ROOT.parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.action == "refresh":
        try:
            latest = prices.load().index.max().date()
            result = prices.refresh(
                latest - timedelta(days=1), datetime.now(UTC).date() + timedelta(days=2)
            )
        except Exception as exc:  # noqa: BLE001 -- do not print credential-bearing HTTP URLs
            print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
            return 1
        print(result)
    elif args.action == "backtest":
        print(backtest().to_string(index=False))
    else:
        frame = publish()
        print(
            json.dumps(
                {
                    "forecast_id": frame.forecast_id.iloc[0],
                    "publication_status": frame.publication_status.iloc[0],
                    "intervals": len(frame),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
