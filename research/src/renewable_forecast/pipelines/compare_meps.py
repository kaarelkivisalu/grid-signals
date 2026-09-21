"""Does run-addressed NWP remove the lead-34 vintage step?

`reports/openmeteo_vintage.md` measured a +35% jump in nMAE at lead hour 34 and
`ablate_vintage.py` attributed it to the whole-day vintage rather than to the day/night
boundary. MEPS is addressed by run, so one 00z forecast covers every delivery hour and
the step should not merely shrink -- it should have no mechanism left to exist.

The comparison is deliberately an exact A/B. Both arms score **the same rows** from the
same MEPS-augmented design matrix; the only difference is which feature columns the
model may see:

* `openmeteo` -- the shipping feature set, with every `__meps` column dropped.
* `meps` -- the `__meps` columns instead of the Open-Meteo weather block.
* `both` -- everything, which is the configuration a production model would use.

Anything that differed in rows, folds or seeds between the arms would make the lead
curve incomparable, which is the whole quantity of interest.

    uv run python -m renewable_forecast.pipelines.compare_meps

Writes `data/interim/compare_meps.parquet` (nMAE per lead hour per arm) and
`data/interim/compare_meps_overall.parquet` (headline metrics per arm).
"""

import logging

import numpy as np
import pandas as pd

from renewable_forecast import config, paths
from renewable_forecast.evaluation import baselines, metrics
from renewable_forecast.features import assemble
from renewable_forecast.models.quantile import QuantileGBM
from renewable_forecast.pipelines import evaluate, train

logger = logging.getLogger(__name__)

#: The shipping model is the one whose lead curve the question is about. Baselines
#: either ignore the NWP columns entirely or are pure physics, so no arm can move them.
SCORED = QuantileGBM.name

ARMS = ("openmeteo", "meps", "both")

#: Arms that need the IFS single-run block as well (`--ifs`).
#:
#: * `runs` -- only run-addressed weather: MEPS, IFS HRES and their cross-source spread.
#:   No column in it changes vintage mid-day.
#: * `runs_om_spread` -- `runs` plus the Open-Meteo *disagreement* columns only. Keeps
#:   the three-model spread signal (`reports/calibration.md`) without its stale levels.
#: * `all` -- everything.
IFS_ARMS = ("runs", "runs_om_spread", "all")

#: Open-Meteo columns that describe disagreement between its models, not their level.
OM_SPREAD_SUFFIXES = ("_model_std", "_model_range")

#: The lead hour where the whole-day vintage forces a change of forecast age.
STEP_LEAD = 34

#: Weather columns from the Open-Meteo block. Identified by exclusion: anything that is
#: not MEPS, not the target, and not bookkeeping shared by both arms.
SHARED_PREFIXES = ("cf_lag_", "hour_", "doy_")
SHARED_COLUMNS = frozenset(
    {
        "cf",
        "mw",
        "capacity_mw",
        "valid_time",
        "delivery_day",
        "issue_day",
        "season",
        "lead_hour",
        "nwp_offset_days",
        "meps_run_time",
        "ifs_run_time",
    }
)


def _is_shared(column: str) -> bool:
    return column in SHARED_COLUMNS or column.startswith(SHARED_PREFIXES)


def arm_columns(frame: pd.DataFrame, arm: str) -> list[str]:
    """Columns retained for one arm of the comparison."""
    # `meps_run_time` is MEPS-marked but is bookkeeping every arm needs, so it counts
    # as shared; without this the `both` arm would list it twice.
    shared = [c for c in frame.columns if _is_shared(c)]
    rest = [c for c in frame.columns if not _is_shared(c)]
    # A column built from IFS belongs to the IFS side even if it also carries the MEPS
    # marker (the cross-source spread), or the MEPS arm would see IFS information.
    ifs = [c for c in rest if assemble.is_ifs_column(c)]
    meps = [c for c in rest if assemble.is_meps_column(c) and c not in ifs]
    weather = [c for c in rest if c not in ifs and c not in meps]
    om_spread = [c for c in weather if c.endswith(OM_SPREAD_SUFFIXES)]
    arms = {
        "openmeteo": shared + weather,
        "meps": shared + meps,
        "both": shared + weather + meps,
        "runs": shared + meps + ifs,
        "runs_om_spread": shared + meps + ifs + om_spread,
        "all": shared + weather + meps + ifs,
    }
    if arm not in arms:
        msg = f"unknown arm {arm}"
        raise ValueError(msg)
    return arms[arm]


def covered(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows where MEPS is present, so every arm sees an identical row set.

    Restricting up front rather than per arm is the point: an arm scored on more days
    than another would differ by sample, not by information.
    """
    have = frame["power_curve__meps"].notna()
    days = frame.loc[have, "delivery_day"].unique()
    complete = frame[frame.delivery_day.isin(days)]
    dropped = frame.delivery_day.nunique() - complete.delivery_day.nunique()
    if dropped:
        logger.info("%s delivery days lack MEPS coverage and are excluded", dropped)
    return complete.reset_index(drop=True)


def development_days(frame: pd.DataFrame, cfg: config.Config) -> pd.DatetimeIndex:
    """Development days of the *full* calendar that the MEPS frame covers.

    The holdout is sealed relative to the full design matrix, which runs to the present.
    Sealing relative to the MEPS frame instead would treat its last six months as
    holdout -- but MEPS is deliberately pulled only up to the real holdout, so that
    would silently discard half a year of development data and score the arms on a
    different window from `modelling.md`.
    """
    development, _ = evaluate.development_split(evaluate.load_design_matrix(), cfg)
    return development[development.isin(frame.delivery_day.unique())]


def score_arm(
    frame: pd.DataFrame,
    arm: str,
    cfg: config.Config,
    development: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Backtest one arm on the frozen protocol.

    Returns nMAE per lead hour and the standard metric bundle.
    """
    levels = np.array(cfg.task.quantiles)
    subset = frame[arm_columns(frame, arm)].copy()

    history = subset.set_index("valid_time").cf
    tso_mw = baselines.TsoForecast.load("SE3", "wind_onshore")
    tso_cf = (tso_mw / subset.set_index("valid_time").capacity_mw).dropna()
    chosen = {
        name: factory
        for name, factory in train.forecasters(levels, history, tso_cf).items()
        if name == SCORED
    }

    actual, context, predictions = evaluate.run_folds(subset, development, chosen, cfg)
    quantiles = predictions[SCORED]
    median = quantiles[:, int(np.argmin(np.abs(levels - 0.5)))]

    by_lead = (
        pd.DataFrame(
            {
                "lead_hour": np.asarray(context.lead_hour),
                "nmae": np.abs(np.asarray(actual) - median),
            }
        )
        .groupby("lead_hour")
        .nmae.mean()
        .reset_index()
    )
    by_lead["arm"] = arm

    bundle = metrics.summarise(actual, quantiles, levels)
    bundle["arm"] = arm
    bundle["rows"] = float(len(actual))
    return by_lead, bundle


def step_at(by_lead: pd.DataFrame, lead: int = STEP_LEAD) -> float:
    """Fractional jump in nMAE across a lead hour -- the quantity being removed.

    The published figure is a +35% step at lead 34 under whole-day vintaging; with a
    run-addressed source there is no mechanism left to produce one.
    """
    curve = by_lead.set_index("lead_hour").nmae
    before = curve.loc[lead - 3 : lead - 1].mean()
    after = curve.loc[lead : lead + 2].mean()
    return float(after / before - 1.0)


def run(*, with_ifs: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Score every arm and summarise by lead hour."""
    cfg = config.load()
    frame = covered(evaluate.load_design_matrix(with_meps=True, with_ifs=with_ifs))
    arms = ARMS + IFS_ARMS if with_ifs else ARMS
    if with_ifs:
        # Same-rows discipline: a day without an IFS run would otherwise be scored by
        # some arms and not others.
        have = frame.groupby("delivery_day")["power_curve__ifsrun"].transform(
            lambda s: s.notna().all()
        )
        frame = frame[have].reset_index(drop=True)
    logger.info(
        "comparing on %s delivery days, %s rows",
        frame.delivery_day.nunique(),
        len(frame),
    )

    development = development_days(frame, cfg)
    logger.info(
        "scoring on %s development days, %s..%s",
        len(development),
        development.min().date(),
        development.max().date(),
    )
    curves, bundles = [], []
    for arm in arms:
        by_lead, bundle = score_arm(frame, arm, cfg, development)
        bundle["step_at_34"] = step_at(by_lead)
        curves.append(by_lead)
        bundles.append(bundle)

    by_lead = pd.concat(curves, ignore_index=True)
    overall = pd.DataFrame(bundles)

    stem = "compare_nwp_runs" if with_ifs else "compare_meps"
    paths.INTERIM.mkdir(parents=True, exist_ok=True)
    by_lead.to_parquet(paths.INTERIM / f"{stem}.parquet", index=False)
    overall.to_parquet(paths.INTERIM / f"{stem}_overall.parquet", index=False)
    logger.info("\n%s", overall.round(4).to_string(index=False))
    return by_lead, overall


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ifs", action="store_true", help="add the IFS single-run arms"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run(with_ifs=args.ifs)


if __name__ == "__main__":
    main()
