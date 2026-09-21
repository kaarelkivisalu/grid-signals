"""Which calibration layer closes the coverage gap?

`lightgbm_quantile` covers 74% at a nominal 80%, and the shortfall is not uniform:
among hours with the same raw interval width, coverage falls from 0.81 where the three
NWP models agree to 0.67 where they disagree most. The current layer stratifies by lead
hour and predicted level, which cannot see that.

This is an exact A/B over calibration alone. Per fold the boosters are fitted **once**,
on the inner part of the training window, and every arm post-processes the same raw
quantiles:

* `raw` -- no calibration, the floor.
* `stratified` -- `StratifiedCQR`, which shipped until 2026-09-22.
* `spread_additive` -- `SpreadCQR` with additive scores. Won, and now ships.
* `spread_scaled` -- `SpreadCQR` with width-normalised scores.
* `spread_scaled_refit` -- as above, but the boosters are then refitted on the whole
  training window, calibration days included, and the correction learned from the inner
  model is applied to the refitted one. It spends the most recent quarter of data on
  the forecast as well as on calibration, at the risk that a model fitted on more data
  is sharper than the one the correction was measured on.

    uv run python -m renewable_forecast.pipelines.compare_calibration

Writes `data/interim/compare_calibration.parquet` (per-row quantiles for every arm) and
`data/interim/compare_calibration_overall.parquet` (headline metrics per arm).
"""

import argparse
import logging

import numpy as np
import pandas as pd

from renewable_forecast import config, paths
from renewable_forecast.evaluation import metrics, splits
from renewable_forecast.models.conformal import SpreadCQR, StratifiedCQR
from renewable_forecast.models.quantile import QuantileGBM
from renewable_forecast.pipelines import evaluate

logger = logging.getLogger(__name__)

ARMS = (
    "raw",
    "stratified",
    "spread_additive",
    "spread_scaled",
    "spread_scaled_refit",
)

#: Row context kept alongside every arm's quantiles, for the conditional breakdowns.
CONTEXT = [
    "valid_time",
    "delivery_day",
    "lead_hour",
    "season",
    "cf",
    "capacity_mw",
    "power_curve_model_std",
]


def _fold_arms(
    train: pd.DataFrame, test: pd.DataFrame, levels: np.ndarray
) -> dict[str, np.ndarray]:
    inner, calib = splits.calibration_split(train)
    model = QuantileGBM(levels, conformalise=False).fit(inner)
    raw_calib, raw_test = model.predict(calib), model.predict(test)

    arms = {"raw": raw_test}
    arms["stratified"] = (
        StratifiedCQR(levels).fit(calib, raw_calib).apply(test, raw_test)
    )
    arms["spread_additive"] = (
        SpreadCQR(levels, normalise=False).fit(calib, raw_calib).apply(test, raw_test)
    )
    scaled = SpreadCQR(levels).fit(calib, raw_calib)
    arms["spread_scaled"] = scaled.apply(test, raw_test)

    refit = QuantileGBM(levels, conformalise=False).fit(train)
    arms["spread_scaled_refit"] = scaled.apply(test, refit.predict(test))
    return arms


def conditional_coverage(frame: pd.DataFrame, by: str) -> pd.DataFrame:
    """80% coverage and mean p10-p90 width per arm within groups of `by`."""
    inside = (frame.cf >= frame["q0.10"]) & (frame.cf <= frame["q0.90"])
    return (
        frame.assign(inside=inside, width=frame["q0.90"] - frame["q0.10"])
        .groupby(["arm", by], observed=True)
        .agg(n=("cf", "size"), cov80=("inside", "mean"), width80=("width", "mean"))
        .reset_index()
    )


def run(arms: tuple[str, ...] = ARMS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Score every calibration arm on identical rows and folds."""
    cfg = config.load()
    levels = np.array(cfg.task.quantiles)
    frame = evaluate.load_design_matrix()
    development, _ = evaluate.development_split(frame, cfg)
    folds = splits.rolling_origin(
        development, cfg.splits.embargo_days, cfg.splits.origin_freq, min_train_days=180
    )

    collected: dict[str, list[np.ndarray]] = {arm: [] for arm in arms}
    context = []
    for number, fold in enumerate(folds, 1):
        train = frame[frame.delivery_day.isin(fold.train_days)]
        test = frame[frame.delivery_day.isin(fold.test_days)]
        if train.empty or test.empty:
            continue
        produced = _fold_arms(train, test, levels)
        for arm in arms:
            collected[arm].append(produced[arm])
        context.append(test[[c for c in CONTEXT if c in test.columns]])
        logger.info("fold %s/%s done", number, len(folds))

    rows = pd.concat(context, ignore_index=True)
    actual = rows.cf.to_numpy()
    bundles, long = [], []
    for arm in arms:
        quantiles = np.vstack(collected[arm])
        bundle = metrics.summarise(actual, quantiles, levels)
        bundles.append({"arm": arm, **bundle})
        per_row = rows.copy()
        per_row.insert(0, "arm", arm)
        for level, column in zip(levels, quantiles.T, strict=True):
            per_row[f"q{level:.2f}"] = column
        long.append(per_row)

    overall = pd.DataFrame(bundles)
    per_row = pd.concat(long, ignore_index=True)
    paths.INTERIM.mkdir(parents=True, exist_ok=True)
    per_row.to_parquet(paths.INTERIM / "compare_calibration.parquet", index=False)
    overall.to_parquet(
        paths.INTERIM / "compare_calibration_overall.parquet", index=False
    )
    logger.info("\n%s", overall.round(4).to_string(index=False))
    return per_row, overall


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arms", nargs="*", default=list(ARMS))
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run(tuple(args.arms))


if __name__ == "__main__":
    main()
