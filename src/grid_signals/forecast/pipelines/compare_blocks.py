"""Do the issue-time feature blocks earn their place? (roadmap D1, D2).

An exact A/B, like `compare_meps`: every arm is the shipping quantile model on the same
rows and folds, and the arms differ only in which feature blocks are appended.

* `base` -- the design matrix as it stands.
* `prices` -- plus the issue day's day-ahead prices (curtailment risk).
* `residuals` -- plus the recent physics-residual anomalies.
* `both` -- plus both.

Negative-price hours are scored separately, because that is where the price block
should act and a pooled metric would dilute it 25-fold.

    uv run python -m grid_signals.forecast.pipelines.compare_blocks [--meps] [--ifs]

Writes `data/interim/compare_blocks_overall.parquet`.
"""

import argparse
import logging

import numpy as np
import pandas as pd

from grid_signals.forecast import config, paths
from grid_signals.forecast.evaluation import metrics
from grid_signals.forecast.features import assemble, sites
from grid_signals.forecast.models.quantile import QuantileGBM
from grid_signals.forecast.pipelines import compare_meps, evaluate

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
        rows.append(
            {"arm": arm, "rows": "all", **metrics.summarise(actual, quantiles, levels)}
        )
        mask = context.valid_time.map(negative).fillna(value=False).to_numpy(dtype=bool)
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


def is_lagged_column(column: str) -> bool:
    """Whether a column comes from the previous day's 18z IFS run."""
    return assemble.LAG_SUFFIX in column or column.endswith(("_jump", "_jump_abs"))


def run_lagged_ifs() -> pd.DataFrame:
    """Base configured matrix against base + the 18z lagged-IFS block (roadmap B5).

    Restricted to delivery days where the 18z run exists (from 2024-08-06), so that
    neither arm is fitted across the boundary where the block appears.
    """
    cfg = config.load()
    levels = np.array(cfg.task.quantiles)
    sources = tuple(cfg.features.get("run_addressed", ()))
    frame = evaluate.load_design_matrix(**assemble.run_flags(sources))
    frame = assemble.require_run_coverage(frame, sources)
    frame = assemble._attach_lagged_ifs(frame, sites.build(cfg.task.zone))  # noqa: SLF001
    have = frame["power_curve__ifsrun_lag6"].notna().groupby(frame.delivery_day)
    frame = frame[have.transform("all")].reset_index(drop=True)
    development = compare_meps.development_days(frame, cfg)
    logger.info("%s delivery days with an 18z run", frame.delivery_day.nunique())

    rows = []
    for arm in ("base", "lagged_ifs"):
        subset = frame[
            [c for c in frame.columns if arm == "lagged_ifs" or not is_lagged_column(c)]
        ]
        actual, context, predictions = evaluate.run_folds(
            subset, development, {QuantileGBM.name: lambda: QuantileGBM(levels)}, cfg
        )
        quantiles = predictions[QuantileGBM.name]
        rows.append({"arm": arm, **metrics.summarise(actual, quantiles, levels)})
        # The block exists to flag unstable forecasts; score where it says so.
        jump = frame.set_index("valid_time")["power_curve__ifsrun_jump_abs"]
        jumpy = (context.valid_time.map(jump) > 0.1).to_numpy()
        rows.append(
            {
                "arm": f"{arm} | jump > 0.1",
                "n": int(jumpy.sum()),
                **metrics.summarise(actual[jumpy], quantiles[jumpy], levels),
            }
        )
    overall = pd.DataFrame(rows)
    overall.to_parquet(
        paths.INTERIM / "compare_lagged_ifs_overall.parquet", index=False
    )
    logger.info("\n%s", overall.round(4).to_string(index=False))
    return overall


def run_drop(columns: tuple[str, ...]) -> pd.DataFrame:
    """Configured matrix with and without `columns`, same rows and folds.

    Scored pooled and per season, because the question that motivated it -- do the
    day-of-year terms memorise one year's seasonal anomaly? -- shows up as seasonal
    bias, not in the pooled score.
    """
    cfg = config.load()
    levels = np.array(cfg.task.quantiles)
    sources = tuple(cfg.features.get("run_addressed", ()))
    frame = evaluate.load_design_matrix(**assemble.run_flags(sources))
    frame = assemble.require_run_coverage(frame, sources)
    development = compare_meps.development_days(frame, cfg)
    missing = set(columns) - set(frame.columns)
    if missing:
        msg = f"columns not in the matrix: {sorted(missing)}"
        raise ValueError(msg)

    rows = []
    for arm, subset in (
        ("base", frame),
        ("dropped", frame.drop(columns=list(columns))),
    ):
        actual, context, predictions = evaluate.run_folds(
            subset, development, {QuantileGBM.name: lambda: QuantileGBM(levels)}, cfg
        )
        quantiles = predictions[QuantileGBM.name]
        rows.append(
            {
                "arm": arm,
                "season": "all",
                **metrics.summarise(actual, quantiles, levels),
            }
        )
        for season in ("DJF", "MAM", "JJA", "SON"):
            mask = (context.season == season).to_numpy()
            rows.append(
                {
                    "arm": arm,
                    "season": season,
                    **metrics.summarise(actual[mask], quantiles[mask], levels),
                }
            )
    overall = pd.DataFrame(rows)
    overall.to_parquet(paths.INTERIM / "compare_drop_overall.parquet", index=False)
    logger.info("dropped %s\n%s", columns, overall.round(4).to_string(index=False))
    return overall


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meps", action="store_true")
    parser.add_argument("--ifs", action="store_true")
    parser.add_argument("--lagged-ifs", action="store_true")
    parser.add_argument(
        "--drop", nargs="*", help="A/B the matrix without these columns"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if args.drop:
        run_drop(tuple(args.drop))
    elif args.lagged_ifs:
        run_lagged_ifs()
    else:
        run(with_meps=args.meps or args.ifs, with_ifs=args.ifs)


if __name__ == "__main__":
    main()
