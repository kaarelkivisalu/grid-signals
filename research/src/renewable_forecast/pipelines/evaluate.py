"""The shared scoring loop.

Baselines and learned models run through exactly the same folds, on exactly the same
rows, and are logged the same way -- otherwise the leaderboard compares apples to
different apples.
"""

import logging
from collections.abc import Callable

import numpy as np
import pandas as pd

from renewable_forecast import config, experiment, paths
from renewable_forecast.evaluation import metrics, splits

logger = logging.getLogger(__name__)

#: A forecaster is anything that can be fitted on a train frame and predict quantiles.
Forecaster = Callable[[], object]


def load_design_matrix(zone: str = "SE3", fuel: str = "wind_onshore") -> pd.DataFrame:
    """Read the design matrix built in Phase 4."""
    path = paths.FEATURES / f"design_matrix_{zone.lower()}_{fuel}.parquet"
    if not path.exists():
        msg = f"{path} missing; run renewable_forecast.features.assemble first"
        raise FileNotFoundError(msg)
    frame = pd.read_parquet(path)
    frame["valid_time"] = pd.to_datetime(frame.valid_time, utc=True)
    frame["delivery_day"] = pd.to_datetime(frame.delivery_day)
    return frame.sort_values("valid_time").reset_index(drop=True)


def development_split(
    frame: pd.DataFrame, cfg: config.Config
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Separate the sealed holdout from the development set."""
    days = pd.DatetimeIndex(sorted(frame.delivery_day.unique()))
    development, holdout = splits.seal_holdout(days, cfg.splits.holdout_months)
    logger.info(
        "development %s..%s (%sd) | holdout %s..%s (%sd) SEALED",
        development.min().date(),
        development.max().date(),
        len(development),
        holdout.min().date(),
        holdout.max().date(),
        len(holdout),
    )
    return development, holdout


def run_folds(
    frame: pd.DataFrame,
    days: pd.DatetimeIndex,
    forecasters: dict[str, Forecaster],
    cfg: config.Config,
) -> tuple[np.ndarray, pd.DataFrame, dict[str, np.ndarray]]:
    """Fit and predict every forecaster across the rolling-origin folds."""
    folds = splits.rolling_origin(
        days, cfg.splits.embargo_days, cfg.splits.origin_freq, min_train_days=180
    )
    logger.info("%s folds", len(folds))

    collected: dict[str, list[np.ndarray]] = {name: [] for name in forecasters}
    truth, context = [], []
    for fold in folds:
        train = frame[frame.delivery_day.isin(fold.train_days)]
        test = frame[frame.delivery_day.isin(fold.test_days)]
        if train.empty or test.empty:
            continue
        for name, factory in forecasters.items():
            collected[name].append(factory().fit(train).predict(test))
        truth.append(test.cf.to_numpy())
        context.append(test)

    if not truth:
        msg = "no usable folds; the development window is too short"
        raise RuntimeError(msg)
    return (
        np.concatenate(truth),
        pd.concat(context, ignore_index=True),
        {name: np.vstack(preds) for name, preds in collected.items()},
    )


def score(
    name: str,
    actual: np.ndarray,
    quantiles: np.ndarray,
    levels: np.ndarray,
    context: pd.DataFrame,
    cfg: config.Config,
    kind: str = "model",
) -> dict:
    """Score one forecaster and log it to MLflow."""
    point = quantiles[:, int(np.argmin(np.abs(levels - 0.5)))]
    scored = context.assign(point=point)
    summary = metrics.summarise(actual, quantiles, levels)

    with experiment.run(name, cfg, kind=kind):
        experiment.log_metrics(summary)
        for group in ("lead_hour", "season"):
            if group in scored.columns:
                experiment.log_table(
                    metrics.by_segment(scored, "cf", "point", group), f"by_{group}"
                )
        experiment.log_table(
            pd.DataFrame(
                {
                    "level": levels,
                    "pinball": metrics.pinball(actual, quantiles, levels),
                }
            ),
            "pinball_by_level",
        )
        experiment.log_table(
            pd.DataFrame({"pit": metrics.pit(actual, quantiles, levels)}), "pit"
        )
    logger.info("%-24s crps=%.4f nmae=%.4f", name, summary["crps"], summary["nmae"])
    return {"name": name, **summary}


def leaderboard(
    rows: list[dict],
    actual: np.ndarray,
    predictions: dict[str, np.ndarray],
    levels: np.ndarray,
    context: pd.DataFrame,
    reference: str = "climatology",
) -> pd.DataFrame:
    """Rank forecasters and attach a day-block bootstrap CI on the CRPS difference."""
    table = pd.DataFrame(rows).sort_values("crps").reset_index(drop=True)
    if reference not in predictions:
        return table

    import scoringrules as sr

    baseline_loss = sr.crps_quantile(actual, predictions[reference], levels)
    days = context.delivery_day
    lows, highs, reference_crps = [], [], float(np.nanmean(baseline_loss))
    for name in table.name:
        loss = sr.crps_quantile(actual, predictions[name], levels)
        low, high = splits.bootstrap_ci(pd.Series(loss - baseline_loss), days)
        lows.append(low)
        highs.append(high)
    table["crpss_vs_" + reference] = [
        metrics.skill_score(c, reference_crps) for c in table.crps
    ]
    # A CI on the *difference* that straddles zero means the gap is not significant.
    table["delta_ci_low"] = lows
    table["delta_ci_high"] = highs
    table["significant"] = (np.array(lows) > 0) | (np.array(highs) < 0)
    return table
