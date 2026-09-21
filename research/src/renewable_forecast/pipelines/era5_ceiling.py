"""How well can SE3 wind generation be explained by the weather that actually happened?

ERA5 is as close to the true weather as any archive gets. A model fitted on it is not a
forecast -- it sees the outcome's weather -- so its error is a *ceiling*: the part of
generation no weather-driven model can ever explain. If that ceiling sits close to the
day-ahead forecast's error, the forecast is not what limits accuracy; the target, the
fleet registry or something unobserved (curtailment, outages, icing) is.

    uv run python -m renewable_forecast.pipelines.era5_ceiling [--rebuild]

Stops at the end of February 2026 -- the holdout is not touched.
"""

import argparse
import logging

import lightgbm as lgb
import numpy as np
import pandas as pd

from renewable_forecast import paths
from renewable_forecast.evaluation import splits
from renewable_forecast.features import era5_fleet, sites
from renewable_forecast.sources import era5, fleet

logger = logging.getLogger(__name__)

FEATURES_PATH = paths.INTERIM / "era5_features_se3.parquet"
TARGETS_PATH = paths.INTERIM / "targets_se3_wind_onshore.parquet"
BACKTEST_PATH = paths.PREDICTIONS / "backtest_se3_wind_onshore.parquet"
REPORT_PATH = paths.REPORTS / "era5_ceiling_tables.md"
RESULTS_PATH = paths.INTERIM / "era5_ceiling_predictions.parquet"

DESIGN_MATRIX_PATH = paths.FEATURES / "design_matrix_se3_wind_onshore.parquet"
MATCHED_PATH = paths.INTERIM / "era5_ceiling_matched.parquet"

END = pd.Timestamp("2026-03-01", tz="UTC")

#: The fleet that already existed when the ERA5 period starts. Its output is the
#: reference against which capacity added later is judged.
REFERENCE_FLEET_BEFORE = pd.Timestamp("2018-01-01", tz="UTC")

#: Training-window starts for the backtest-matched folds. `forecast_archive` is the
#: day-ahead model's own window, so it is the like-for-like comparison.
TRAIN_STARTS = {
    "era5_all_history": pd.Timestamp("2018-01-01", tz="UTC"),
    "era5_forecast_archive": pd.Timestamp("2024-02-16", tz="UTC"),
}

WEATHER = [
    "temperature",
    "humidity",
    "alpha",
    "density",
    "icing",
    "speed_100",
    "boundary_layer_height",
    "direction_sin",
    "direction_cos",
    "speed_hub_spatial_std",
]
CLUSTERS = [f"c{k}_{s}" for k in range(8) for s in ("cf", "speed_hub")]
PHYSICS = ["phys_generic_cf", "phys_specific_cf", "phys_smooth_cf"]
CALENDAR = ["hour", "doy_sin", "doy_cos"]

GBM_PARAMS = {
    "objective": "l1",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "verbose": -1,
}
GBM_ROUNDS = 800


def build_features() -> pd.DataFrame:
    grid = era5.load_cells()
    turbines = era5_fleet.turbine_table(fleet.load_turbines())
    clusters = sites.build("SE3")
    instants = era5_fleet.build(grid, turbines, clusters)
    reference = turbines[turbines.commissioned < REFERENCE_FLEET_BEFORE]
    instants["phys_smooth_reference_mw"] = era5_fleet.build(
        grid, reference.reset_index(drop=True), clusters
    ).phys_smooth_mw.to_numpy()
    hourly = era5_fleet.to_hourly_intervals(instants)
    hourly.to_parquet(FEATURES_PATH, index=False)
    logger.info("wrote %s (%s rows)", FEATURES_PATH, len(hourly))
    return hourly


def dataset(features: pd.DataFrame) -> pd.DataFrame:
    targets = pd.read_parquet(TARGETS_PATH)
    frame = targets.merge(features, on="period_start", how="inner")
    frame = frame[frame.trainable & (frame.period_start < END)].copy()
    for name in ("generic", "specific", "smooth"):
        frame[f"phys_{name}_cf"] = frame[f"phys_{name}_mw"] / frame.live_capacity_mw
    # The target is normalised by the *same* live fleet the physics used, so the model
    # never has to learn a capacity trend.
    frame["cf_live"] = frame.mw / frame.live_capacity_mw
    stamp = frame.period_start
    frame["hour"] = stamp.dt.hour
    frame["year"] = stamp.dt.year
    doy = 2 * np.pi * stamp.dt.dayofyear / 365.25
    frame["doy_sin"] = np.sin(doy)
    frame["doy_cos"] = np.cos(doy)
    return frame.reset_index(drop=True)


def scores(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    error = predicted - actual
    return {
        "mae_mw": float(error.abs().mean()),
        "rmse_mw": float(np.sqrt((error**2).mean())),
        "bias_mw": float(error.mean()),
        "r2": float(1 - (error**2).sum() / ((actual - actual.mean()) ** 2).sum()),
        "corr": float(np.corrcoef(actual, predicted)[0, 1]),
    }


def fit_gbm(train: pd.DataFrame, columns: list[str]) -> lgb.Booster:
    data = lgb.Dataset(train[columns], train.cf_live)
    return lgb.train(GBM_PARAMS, data, GBM_ROUNDS)


def leave_one_year_out(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Out-of-sample predictions in MW, each year scored by a model that never saw it."""
    out = pd.Series(np.nan, index=frame.index)
    for year in sorted(frame.year.unique()):
        test = frame.year == year
        model = fit_gbm(frame[~test], columns)
        out[test] = (
            model.predict(frame.loc[test, columns]) * frame.live_capacity_mw[test]
        )
    return out


def scaled_physics(frame: pd.DataFrame, column: str) -> pd.Series:
    """Physics with a single fitted gain per held-out year -- a calibration, not a model."""
    out = pd.Series(np.nan, index=frame.index)
    for year in sorted(frame.year.unique()):
        test = frame.year == year
        train = frame[~test]
        gain = (train.cf_live * train[column]).sum() / (train[column] ** 2).sum()
        out[test] = gain * frame.loc[test, column] * frame.live_capacity_mw[test]
    return out


def best_lag(frame: pd.DataFrame, column: str) -> pd.Series:
    """Correlation of the target with the physics shifted by -3..+3 hours."""
    series = frame.set_index("period_start")
    return pd.Series(
        {
            lag: series.cf_live.corr(
                series[column].shift(lag, freq="h").reindex(series.index)
            )
            for lag in range(-3, 4)
        }
    )


def _table(frame: pd.DataFrame, methods: list[str]) -> pd.DataFrame:
    rows = [
        {"method": m, "n": len(frame), **scores(frame.mw, frame[m])} for m in methods
    ]
    return pd.DataFrame(rows)


def _md(frame: pd.DataFrame) -> str:
    def cell(value) -> str:
        return f"{value:.3g}" if isinstance(value, float) else str(value)

    header = "| " + " | ".join(map(str, frame.columns)) + " |"
    rule = "|" + "---|" * len(frame.columns)
    rows = [
        "| " + " | ".join(cell(v) for v in row) + " |"
        for row in frame.itertuples(index=False)
    ]
    return "\n".join([header, rule, *rows])


def matched_folds(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """ERA5 models scored on exactly the backtest's folds and hours.

    Fold geometry is rebuilt with `splits.rolling_origin` from the design matrix's
    development days, as `pipelines/evaluate.py` does, so each test month is predicted
    by a model trained only on what the day-ahead model had at that origin.
    """
    design_days = pd.DatetimeIndex(
        sorted(
            pd.read_parquet(
                DESIGN_MATRIX_PATH, columns=["delivery_day"]
            ).delivery_day.unique()
        )
    )
    development, _ = splits.seal_holdout(design_days)
    folds = splits.rolling_origin(development, min_train_days=180)

    backtest = pd.read_parquet(BACKTEST_PATH)
    backtest = (
        backtest.pivot_table(
            index=["valid_time", "delivery_day"],
            columns="forecaster",
            values="mw_q0.50",
        )
        .rename_axis(None, axis=1)
        .reset_index()
    )
    indexed = frame.set_index("period_start")

    parts = []
    for fold in folds:
        rows = backtest[backtest.delivery_day.isin(fold.test_days)]
        rows = rows[rows.valid_time.isin(indexed.index)]
        if rows.empty:
            continue
        test = indexed.loc[rows.valid_time]
        train_end = pd.Timestamp(fold.train_days.max(), tz="UTC") + pd.Timedelta(days=1)
        out = rows.copy()
        for name, start in TRAIN_STARTS.items():
            train = frame[
                (frame.period_start >= start) & (frame.period_start < train_end)
            ]
            model = fit_gbm(train, columns)
            out[name] = model.predict(test[columns]) * test.live_capacity_mw.to_numpy()
        out["mw"] = test.mw.to_numpy()
        parts.append(out)
    return pd.concat(parts, ignore_index=True).rename(
        columns={"valid_time": "period_start"}
    )


def yield_ratio(frame: pd.DataFrame) -> pd.DataFrame:
    """Actual over physically expected output per quarter, and what that implies.

    Weather is held fixed by construction, so a trend here is not windier or calmer
    years. Splitting expected output into the pre-2018 reference fleet and everything
    added since, and holding the reference fleet at its 2018 gain, gives the gain the
    added capacity would need to explain the rest.
    """
    series = frame.set_index("period_start")
    first_year = series[series.index.year == series.index.year.min()]
    reference_gain = first_year.mw.sum() / first_year.phys_smooth_reference_mw.sum()
    quarterly = series.resample("QS").agg(
        {
            "mw": "sum",
            "phys_smooth_mw": "sum",
            "phys_smooth_reference_mw": "sum",
            "live_capacity_mw": "last",
        }
    )
    added = quarterly.phys_smooth_mw - quarterly.phys_smooth_reference_mw
    return pd.DataFrame(
        {
            "quarter": quarterly.index.strftime("%Y-Q")
            + quarterly.index.quarter.astype(str),
            "live_capacity_mw": quarterly.live_capacity_mw,
            "actual / physics": quarterly.mw / quarterly.phys_smooth_mw,
            "added share of expected": added / quarterly.phys_smooth_mw,
            "implied gain of added capacity": (
                quarterly.mw - reference_gain * quarterly.phys_smooth_reference_mw
            )
            / added,
        }
    ).reset_index(drop=True)


def timing(frame: pd.DataFrame) -> pd.DataFrame:
    """Correlation of target and physics with the physics shifted by fractions of an hour.

    Split by era so that a timestamp error introduced by the 15-minute switch in
    December 2025 would show up as a moved peak.
    """
    series = frame.set_index("period_start")
    physics = series.phys_smooth_cf
    eras = {
        "2018-2021": series.index < "2022",
        "2022-2024": (series.index >= "2022") & (series.index < "2025"),
        "2025 Jan-Nov": (series.index >= "2025") & (series.index < "2025-12-01"),
        "Dec 2025 on (15-min)": series.index >= "2025-12-01",
    }
    rows = []
    for shift in np.arange(-1.0, 1.51, 0.25):
        row = {"shift_h": shift}
        for name, mask in eras.items():
            target = series.cf_live[mask]
            stamps = (target.index - pd.to_timedelta(shift, "h")).asi8
            shifted = np.interp(stamps, physics.index.asi8, physics.to_numpy())
            row[name] = target.corr(pd.Series(shifted, index=target.index))
        rows.append(row)
    return pd.DataFrame(rows)


def breakdowns(frame: pd.DataFrame, matched: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Where the ceiling's error sits, next to the day-ahead model's on the same hours."""
    joined = matched.merge(
        frame[
            ["period_start", "temperature", "icing", "phys_smooth_cf", "price_eur_mwh"]
        ],
        on="period_start",
    )
    joined["ceiling"] = joined.era5_forecast_archive - joined.mw
    joined["forecast"] = joined.lightgbm_quantile - joined.mw
    total = joined.ceiling.abs().sum()
    groupings = {
        "temperature_c": pd.cut(joined.temperature, [-40, -10, -5, -2, 0, 2, 5, 40]),
        "icing_share_of_fleet": pd.cut(joined.icing, [-0.01, 0.0, 0.25, 0.5, 1.0]),
        "expected_cf": pd.cut(
            joined.phys_smooth_cf, [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0]
        ),
        "price_eur_mwh": pd.cut(joined.price_eur_mwh, [-500, -0.01, 5, 20, 1e4]),
        "month": joined.period_start.dt.month,
    }
    out = {}
    for name, key in groupings.items():
        grouped = joined.groupby(key, observed=True)
        table = grouped.agg(
            n=("mw", "size"),
            mean_mw=("mw", "mean"),
            ceiling_bias=("ceiling", "mean"),
            ceiling_mae=("ceiling", lambda e: e.abs().mean()),
            forecast_mae=("forecast", lambda e: e.abs().mean()),
        )
        table["share_of_ceiling_error"] = (
            grouped.ceiling.apply(lambda e: e.abs().sum()) / total
        )
        out[f"by_{name}"] = table.rename_axis(name).reset_index().astype({name: str})

    daily = joined.set_index("period_start")[["ceiling", "forecast"]]
    by_day = daily.abs().resample("D").sum().ceiling.sort_values(ascending=False)
    out["error_concentration"] = pd.DataFrame(
        {
            "worst share of days": ["1%", "5%", "10%"],
            "share of ceiling abs error": [
                by_day.head(max(1, int(len(by_day) * q))).sum() / by_day.sum()
                for q in (0.01, 0.05, 0.10)
            ],
        }
    )
    means = daily.resample("D").mean()
    out["shared_error"] = pd.DataFrame(
        {
            "resolution": ["hourly", "daily mean"],
            "corr(forecast error, ceiling error)": [
                daily.forecast.corr(daily.ceiling),
                means.forecast.corr(means.ceiling),
            ],
        }
    )
    return out


def write_report(tables: dict[str, pd.DataFrame]) -> None:
    sections = [f"## {name}\n\n{_md(table)}\n" for name, table in tables.items()]
    REPORT_PATH.write_text(
        "# ERA5 ceiling — generated tables\n\n"
        "Written by `pipelines/era5_ceiling.py`; interpretation lives in "
        "`reports/era5_ceiling.md`.\n\n" + "\n".join(sections)
    )
    logger.info("wrote %s", REPORT_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    features = (
        pd.read_parquet(FEATURES_PATH)
        if FEATURES_PATH.exists() and not args.rebuild
        else build_features()
    )
    frame = dataset(features)
    logger.info(
        "%s hours, %s .. %s",
        len(frame),
        frame.period_start.min(),
        frame.period_start.max(),
    )
    columns = PHYSICS + WEATHER + CLUSTERS + CALENDAR

    # Long history: every year scored by a model that never saw it. No capacity trend
    # can be learned this way, which is the point -- the bias by year exposes it.
    history = pd.DataFrame({"period_start": frame.period_start, "mw": frame.mw})
    for name in ("generic", "specific", "smooth"):
        history[f"physics_{name}"] = frame[f"phys_{name}_mw"]
    history["physics_smooth_scaled"] = scaled_physics(frame, "phys_smooth_cf")
    history["gbm_physics_only"] = leave_one_year_out(frame, PHYSICS)
    history["gbm_full"] = leave_one_year_out(frame, columns)
    history.to_parquet(RESULTS_PATH, index=False)

    matched = matched_folds(frame, columns)
    matched.to_parquet(MATCHED_PATH, index=False)
    forecasters = [
        c
        for c in matched.columns
        if c not in {"period_start", "delivery_day", "mw", "climatology", "persistence"}
    ]

    methods = [c for c in history.columns if c not in {"period_start", "mw"}]
    tables = {
        "leave_one_year_out_2018_2026": _table(history, methods),
        "leave_one_year_out_bias_by_year": history.assign(
            year=history.period_start.dt.year
        )
        .groupby("year")
        .apply(lambda g: pd.Series(scores(g.mw, g.gbm_full)), include_groups=False)
        .reset_index(),
        "backtest_matched": _table(matched, forecasters),
        "yield_ratio": yield_ratio(frame),
        "timing": timing(frame),
        **breakdowns(frame, matched),
    }
    write_report(tables)
    for name in ("leave_one_year_out_2018_2026", "backtest_matched", "shared_error"):
        print(f"\n{name}\n{tables[name].to_string(index=False)}")


if __name__ == "__main__":
    main()
