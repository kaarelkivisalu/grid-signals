"""Score every forecaster on the frozen protocol and put it on the leaderboard.

Run this before any learned model exists: the point of the protocol is that the
scoreboard and its references are fixed in advance, so a model cannot be evaluated
against a bar that moved to accommodate it.
"""

import logging

import numpy as np
import pandas as pd

from renewable_forecast import config, experiment, paths
from renewable_forecast.evaluation import baselines, metrics, splits

logger = logging.getLogger(__name__)


def load_design_matrix(zone: str, fuel: str) -> pd.DataFrame:
    """Read the design matrix built in Phase 4.

    It already carries the task columns (delivery day, lead hour, season) and the NWP
    features, so the baselines and the models are scored on exactly the same rows.
    """
    path = paths.FEATURES / f"design_matrix_{zone.lower()}_{fuel}.parquet"
    if not path.exists():
        msg = f"{path} missing; run renewable_forecast.features.assemble first"
        raise FileNotFoundError(msg)
    frame = pd.read_parquet(path)
    frame["valid_time"] = pd.to_datetime(frame.valid_time, utc=True)
    frame["delivery_day"] = pd.to_datetime(frame.delivery_day)
    return frame.sort_values("valid_time").reset_index(drop=True)


def _score(
    name: str,
    actual: np.ndarray,
    quantiles: np.ndarray,
    levels: np.ndarray,
    frame: pd.DataFrame,
    cfg: config.Config,
) -> dict:
    point = quantiles[:, int(np.argmin(np.abs(levels - 0.5)))]
    scored = frame.assign(point=point)
    summary = metrics.summarise(actual, quantiles, levels)

    with experiment.run(name, cfg, kind="baseline"):
        experiment.log_metrics(summary)
        for group in ("lead_hour", "season"):
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
    logger.info("%-22s crps=%.4f nmae=%.4f", name, summary["crps"], summary["nmae"])
    return {"name": name, **summary}


def run(zone: str = "SE3", fuel: str = "wind_onshore") -> pd.DataFrame:
    """Fit and score every baseline on the development set."""
    cfg = config.load()
    levels = np.array(cfg.task.quantiles)

    frame = load_design_matrix(zone, fuel)
    history = frame.set_index("valid_time").cf

    days = pd.DatetimeIndex(sorted(frame.delivery_day.unique()))
    development, holdout = splits.seal_holdout(days, cfg.splits.holdout_months)
    logger.info(
        "development %s..%s (%s days); holdout %s..%s SEALED",
        development.min().date(),
        development.max().date(),
        len(development),
        holdout.min().date(),
        holdout.max().date(),
    )

    folds = splits.rolling_origin(
        development, cfg.splits.embargo_days, cfg.splits.origin_freq
    )
    logger.info("%s rolling-origin folds", len(folds))

    tso_mw = baselines.TsoForecast.load(zone, fuel)
    tso_cf = (tso_mw / frame.set_index("period_start").capacity_mw).dropna()

    collected: dict[str, list[np.ndarray]] = {
        "climatology": [],
        "persistence": [],
        "tso": [],
    }
    truth, context = [], []

    for fold in folds:
        train = frame[frame.delivery_day.isin(fold.train_days)]
        test = frame[frame.delivery_day.isin(fold.test_days)]
        if test.empty or train.empty:
            continue
        collected["climatology"].append(
            baselines.Climatology(levels).fit(train).predict(test)
        )
        collected["persistence"].append(
            baselines.Persistence(levels).fit(train, history).predict(test, history)
        )
        collected["tso"].append(
            baselines.TsoForecast(levels).fit(train, tso_cf).predict(test, tso_cf)
        )
        collected["physical"].append(
            baselines.PhysicalPowerCurve(levels).fit(train).predict(test)
        )
        truth.append(test.cf.to_numpy())
        context.append(test)

    actual = np.concatenate(truth)
    scored_frame = pd.concat(context, ignore_index=True)
    display = {
        "climatology": "climatology",
        "persistence": "persistence",
        "tso": baselines.TsoForecast.name,
    }

    rows = [
        _score(display[key], actual, np.vstack(preds), levels, scored_frame, cfg)
        for key, preds in collected.items()
    ]
    table = pd.DataFrame(rows).sort_values("crps").reset_index(drop=True)
    reference = table.loc[table.name == "climatology", "crps"].iloc[0]
    table["crpss_vs_climatology"] = [
        metrics.skill_score(c, reference) for c in table.crps
    ]
    return table


def main() -> int:
    """Score the baselines and print the leaderboard."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    table = run()
    print(table.round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
