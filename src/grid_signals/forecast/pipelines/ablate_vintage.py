"""Ablation: is the lead-34 error step the NWP vintage, or the day/night boundary?

Under a fixed 09:00 UTC issue time, lead hour and clock hour are perfectly collinear, so
the leaderboard alone cannot separate the two things that change at lead 34 --
`nwp_offset_days` flipping 1 to 2, and the delivery day crossing into daylight.

Forcing offset 2 onto *every* lead hour breaks the collinearity. Leads 22-33 then carry
the stale vintage at unchanged clock hours; leads 34-46 are untouched and act as the
control. Writes `data/interim/ablation_vintage.parquet`, which
`reporting.figures.plot_vintage_ablation` draws.
"""

import argparse
import logging

import numpy as np
import pandas as pd

from grid_signals.forecast import config, paths
from grid_signals.forecast.evaluation import baselines
from grid_signals.forecast.features import assemble
from grid_signals.forecast.pipelines import evaluate, train

logger = logging.getLogger(__name__)

#: Only the two forecasters whose error curve the question is about. Climatology and
#: persistence never read the NWP columns, so forcing the offset cannot move them.
SCORED = ("lightgbm_quantile", "physical_power_curve")

FORCED_OFFSET = 2

#: Last lead hour that `previous_day1` can legally serve from a 09:00 UTC issue.
LAST_FRESH_LEAD = 33


def build_forced(offset: int) -> pd.DataFrame:
    """Reassemble the design matrix with every row pinned to one NWP offset."""
    original = assemble.required_offset
    assemble.required_offset = lambda valid_time, _issue_time: pd.Series(
        offset, index=valid_time.index
    )
    try:
        return assemble.build()
    finally:
        assemble.required_offset = original


def score_by_lead(frame: pd.DataFrame, variant: str) -> pd.DataFrame:
    """Backtest on the frozen protocol and return nMAE per lead hour."""
    cfg = config.load()
    levels = np.array(cfg.task.quantiles)
    development, _ = evaluate.development_split(frame, cfg)

    history = frame.set_index("valid_time").cf
    tso_mw = baselines.TsoForecast.load("SE3", "wind_onshore")
    tso_cf = (tso_mw / frame.set_index("valid_time").capacity_mw).dropna()
    chosen = {
        name: forecaster
        for name, forecaster in train.forecasters(levels, history, tso_cf).items()
        if name in SCORED
    }

    actual, context, predictions = evaluate.run_folds(frame, development, chosen, cfg)
    rows = []
    for name, quantiles in predictions.items():
        median = quantiles[:, len(levels) // 2]
        errors = pd.DataFrame(
            {
                "lead_hour": np.asarray(context.lead_hour),
                "ae": np.abs(np.asarray(actual) - median),
            }
        )
        by_lead = errors.groupby("lead_hour").ae.mean().rename("nmae").reset_index()
        by_lead["forecaster"] = name
        by_lead["variant"] = variant
        rows.append(by_lead)
    return pd.concat(rows, ignore_index=True)


def run() -> pd.DataFrame:
    """Score the as-built matrix against one with the offset forced, and persist both."""
    as_built = score_by_lead(
        evaluate.load_design_matrix("SE3", "wind_onshore"), "as_built"
    )
    forced = score_by_lead(build_forced(FORCED_OFFSET), "offset2_everywhere")
    result = pd.concat([as_built, forced], ignore_index=True)
    paths.INTERIM.mkdir(parents=True, exist_ok=True)
    result.to_parquet(paths.INTERIM / "ablation_vintage.parquet", index=False)
    return result


def summarise(result: pd.DataFrame) -> pd.DataFrame:
    """Mean nMAE per forecaster, variant and half of the delivery window."""
    half = np.where(result.lead_hour <= LAST_FRESH_LEAD, "leads 22-33", "leads 34-46")
    return result.assign(half=half).pivot_table(
        index=["forecaster", "half"], columns="variant", values="nmae"
    )


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    table = summarise(run())
    logger.info("%s", table.round(4).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
