"""The shared scoring loop.

Baselines and learned models run through exactly the same folds, on exactly the same
rows, and are logged the same way -- otherwise the leaderboard compares apples to
different apples.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from grid_signals.forecast import config, experiment, paths
from grid_signals.forecast.evaluation import metrics, splits
from grid_signals.forecast.features import assemble

logger = logging.getLogger(__name__)

#: A forecaster is anything that can be fitted on a train frame and predict quantiles.
Forecaster = Callable[[], object]


def load_design_matrix(
    zone: str = "SE3",
    fuel: str = "wind_onshore",
    *,
    with_meps: bool = False,
    with_ifs: bool = False,
) -> pd.DataFrame:
    """Read the design matrix built in Phase 4."""
    path = assemble.design_matrix_path(
        zone, fuel, with_meps=with_meps, with_ifs=with_ifs
    )
    if not path.exists():
        msg = f"{path} missing; run grid_signals.forecast.features.assemble first"
        raise FileNotFoundError(msg)
    frame = pd.read_parquet(path)
    frame["valid_time"] = pd.to_datetime(frame.valid_time, utc=True)
    frame["delivery_day"] = pd.to_datetime(frame.delivery_day)
    if "nwp_max_valid_time" not in frame:
        raise RuntimeError(
            f"{path} predates the weather information-age correction; rebuild it with assemble.write"
        )
    latest = pd.to_datetime(frame.nwp_max_valid_time, utc=True)
    available = latest - pd.to_timedelta(frame.nwp_offset_days * 24, unit="h")
    if (available > assemble.issue_time_of(frame)).any():
        raise RuntimeError(
            f"{path} contains weather newer than issue time; rebuild it with assemble.write"
        )
    return frame.sort_values("valid_time").reset_index(drop=True)


def development_split(
    frame: pd.DataFrame, cfg: config.Config
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Separate the sealed holdout from the development set."""
    days = pd.DatetimeIndex(sorted(frame.delivery_day.unique()))
    if cfg.splits.holdout_start:
        start = pd.Timestamp(cfg.splits.holdout_start)
        end = (
            pd.Timestamp(cfg.splits.holdout_end)
            if cfg.splits.holdout_end
            else days.max()
        )
        development = days[days < start]
        holdout = days[(days >= start) & (days <= end)]
    else:
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


def save_predictions(
    context: pd.DataFrame,
    predictions: dict[str, np.ndarray],
    levels: np.ndarray,
    zone: str,
    fuel: str,
) -> Path:
    """Persist every backtest forecast row so the fan charts plot real output.

    The leaderboard reduces each forecaster to eight numbers. This keeps the forecasts
    themselves -- one row per forecaster and delivery hour, with all 19 quantiles in
    both capacity-factor and MW terms -- so a reader can look at what the model actually
    said on a given day rather than only at how wrong it was on average.
    """
    keep = ["valid_time", "delivery_day", "lead_hour", "season", "cf", "capacity_mw"]
    frames = []
    for name, quantiles in predictions.items():
        frame = context[keep].copy()
        frame.insert(0, "forecaster", name)
        for level, column in zip(levels, quantiles.T, strict=True):
            frame[f"cf_q{level:.2f}"] = column
            frame[f"mw_q{level:.2f}"] = column * frame.capacity_mw
        frames.append(frame)
    out = paths.PREDICTIONS / f"backtest_{zone.lower()}_{fuel}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_parquet(out, index=False)
    logger.info("wrote backtest forecasts to %s", out)
    return out


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
