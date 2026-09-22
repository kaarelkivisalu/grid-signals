"""Do the issue-time feature blocks earn their place? (roadmap D1, D2)

An exact A/B, like `compare_meps`: every arm is the shipping quantile model on the same
rows and folds, and the arms differ only in which feature blocks are appended.

* `base` -- the design matrix as it stands.
* `prices` -- plus the issue day's day-ahead prices (curtailment risk).
* `residuals` -- plus the recent physics-residual anomalies.
* `both` -- plus both.

Negative-price hours are scored separately, because that is where the price block
should act and a pooled metric would dilute it 25-fold.

    uv run python -m renewable_forecast.pipelines.compare_blocks [--meps] [--ifs]

Writes `data/interim/compare_blocks_overall.parquet`.
"""

import argparse
import logging

import numpy as np
import pandas as pd

from renewable_forecast import config, paths
from renewable_forecast.evaluation import metrics
from renewable_forecast.features import assemble
from renewable_forecast.models.quantile import QuantileGBM
from renewable_forecast.pipelines import compare_meps, evaluate

logger = logging.getLogger(__name__)

ARMS = ("base", "prices", "residuals", "both")


def arm_frame(frame: pd.DataFrame, arm: str) -> pd.DataFrame:
    """The matrix one arm trains on: the base columns plus its blocks."""
    keep = [
        c
        for c in frame.columns
        if not (assemble.is_price_column(c) or assemble.is_residual_column(c))
    ]
    if arm in {"prices", "both"}:
        keep += [c for c in frame.columns if assemble.is_price_column(c)]
    if arm in {"residuals", "both"}:
        keep += [c for c in frame.columns if assemble.is_residual_column(c)]
    if arm not in ARMS:
        msg = f"unknown arm {arm}"
        raise ValueError(msg)
    return frame[keep]


def run(*, with_meps: bool = False, with_ifs: bool = False) -> pd.DataFrame:
    """Score every arm on identical rows and folds."""
    cfg = config.load()
    levels = np.array(cfg.task.quantiles)
    frame = evaluate.load_design_matrix(with_meps=with_meps, with_ifs=with_ifs)
    if with_meps:
        frame = compare_meps.covered(frame)
    frame = assemble.attach_residuals(assemble.attach_prices(frame))
    development = compare_meps.development_days(frame, cfg)
    negative = frame.set_index("valid_time")[f"{assemble.PRICE_PREFIX}same_hour"] < 0

    rows = []
    for arm in ARMS:
        subset = arm_frame(frame, arm)
        actual, context, predictions = evaluate.run_folds(
            subset, development, {QuantileGBM.name: lambda: QuantileGBM(levels)}, cfg
        )
        quantiles = predictions[QuantileGBM.name]
        rows.append({"arm": arm, "rows": "all", **metrics.summarise(actual, quantiles, levels)})
        mask = context.valid_time.map(negative).fillna(False).to_numpy(dtype=bool)
        rows.append(
            {
                "arm": arm,
                "rows": "negative_price_issue_day_same_hour",
                "n": int(mask.sum()),
                **metrics.summarise(actual[mask], quantiles[mask], levels),
            }
        )
        logger.info("%s done", arm)

    overall = pd.DataFrame(rows)
    paths.INTERIM.mkdir(parents=True, exist_ok=True)
    overall.to_parquet(paths.INTERIM / "compare_blocks_overall.parquet", index=False)
    logger.info("\n%s", overall.round(4).to_string(index=False))
    return overall


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meps", action="store_true")
    parser.add_argument("--ifs", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run(with_meps=args.meps or args.ifs, with_ifs=args.ifs)


if __name__ == "__main__":
    main()
