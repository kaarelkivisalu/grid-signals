"""Development-only quarter-hour evaluation; never opens the sealed holdout.

Wind Stage 1 compares hourly-trained forecasts on interpolated weather against the
same forecasts repeated four times. Solar compares native 15-minute training against
PV physics, smart persistence and clear-sky climatology. All arms share test rows.
"""

import argparse
import logging
from datetime import date
from itertools import pairwise

import numpy as np
import pandas as pd

from renewable_forecast import config, paths, windows
from renewable_forecast.evaluation import metrics, splits
from renewable_forecast.evaluation.solar import (
    ClearSkyClimatology,
    SmartPersistence,
    SolarPhysical,
)
from renewable_forecast.features import assemble, solar
from renewable_forecast.models.quantile import QuantileGBM
from renewable_forecast.models.solar import SolarQuantileGBM
from renewable_forecast.targets import labels

logger = logging.getLogger(__name__)
DEVELOPMENT_END = pd.Timestamp("2026-03-20")


def complete_days(
    frame: pd.DataFrame, required: list[str], resolution: str = "15min"
) -> pd.DataFrame:
    """Exclude entire days with missing weather, observations or delivery intervals."""
    frame = frame.copy()
    expected = frame.delivery_day.map(
        lambda day: len(
            windows.delivery_day_starts(day.date(), resolution=pd.Timedelta(resolution))
        )
    )
    have = frame.groupby("delivery_day").valid_time.transform("nunique") == expected
    finite = (
        frame[required].notna().all(axis=1).groupby(frame.delivery_day).transform("all")
    )
    return frame[have & finite].reset_index(drop=True)


def ramp_scores(frame: pd.DataFrame, point: np.ndarray) -> dict[str, float]:
    """Score median quarter-hour changes, never differences across days or gaps."""
    scored = frame.assign(point=point).sort_values("valid_time")
    actual_ramp = scored.groupby("delivery_day").cf.diff()
    predicted_ramp = scored.groupby("delivery_day").point.diff()
    valid = scored.groupby("delivery_day").valid_time.diff() == pd.Timedelta("15min")
    magnitude = float((actual_ramp - predicted_ramp).abs()[valid].mean())
    timing = []
    for _, day in scored.groupby("delivery_day"):
        actual = day.cf.diff().abs()
        forecast = day.point.diff().abs()
        if actual.max() > 0:
            timing.append(
                abs(
                    (
                        day.loc[actual.idxmax(), "valid_time"]
                        - day.loc[forecast.idxmax(), "valid_time"]
                    ).total_seconds()
                )
                / 60
            )
    return {
        "ramp_mae_cf": magnitude,
        "peak_ramp_timing_mae_min": float(np.mean(timing)),
    }


def run(
    fuel: str, start: date = date(2025, 12, 1), end: date = date(2026, 3, 1)
) -> pd.DataFrame:
    """Score full monthly folds wholly inside the added development evaluation set."""
    if pd.Timestamp(end) > DEVELOPMENT_END or start >= end:
        raise ValueError(
            "evaluation must end by 2026-03-20 (exclusive); holdout is sealed"
        )
    if start.day != 1 or end.day != 1:
        raise ValueError(
            "product evaluation uses full calendar months; start/end must be month starts"
        )
    cfg = config.load("delu_solar" if fuel == "solar" else None)
    levels = np.array(cfg.task.quantiles)
    if fuel == "solar":
        training = solar.build()
        training = training[training.delivery_day < DEVELOPMENT_END]
        training = complete_days(training, ["cf", "physical_cf", "clear_sky_cf"])
        future = training
        factories = {
            ClearSkyClimatology.name: lambda: ClearSkyClimatology(levels),
            SmartPersistence.name: lambda: SmartPersistence(levels, training),
            SolarPhysical.name: lambda: SolarPhysical(levels),
            SolarQuantileGBM.name: lambda: SolarQuantileGBM(
                levels, **cfg.model.get("quantile", {})
            ),
        }
    elif fuel == "wind_onshore":
        flags = assemble.run_flags(cfg.features.get("run_addressed", ()))
        training = assemble.require_run_coverage(
            assemble.build(**flags), cfg.features.get("run_addressed", ())
        )
        training = training[training.delivery_day < DEVELOPMENT_END]
        labels.write(resolution="15min")
        future = assemble.build(resolution="15min", **flags)
        future = future[
            (future.delivery_day >= pd.Timestamp(start))
            & (future.delivery_day < pd.Timestamp(end))
        ]
        future = complete_days(
            future, ["cf", "power_curve_model_mean", *assemble.RUN_SOURCES.values()]
        )
        factories = {}
    else:
        raise ValueError("fuel must be wind_onshore or solar")

    origins = pd.date_range(start, end, freq="MS")
    collected: dict[str, list[pd.DataFrame]] = {}
    for origin, stop in pairwise(origins):
        train = training[
            training.delivery_day < origin - pd.Timedelta(days=cfg.splits.embargo_days)
        ]
        test = future[(future.delivery_day >= origin) & (future.delivery_day < stop)]
        if train.delivery_day.nunique() < 180 or test.empty:
            raise RuntimeError(
                f"insufficient history or test coverage for {origin.date()}"
            )
        logger.info(
            "%s %s: train %sd, test %sd",
            fuel,
            origin.date(),
            train.delivery_day.nunique(),
            test.delivery_day.nunique(),
        )
        if fuel == "solar":
            predictions = {
                name: factory().fit(train).predict(test)
                for name, factory in factories.items()
            }
        else:
            model = QuantileGBM(levels, **cfg.model.get("quantile", {})).fit(train)
            hourly = training[training.delivery_day.isin(test.delivery_day.unique())]
            hourly_values = pd.DataFrame(model.predict(hourly), index=hourly.valid_time)
            repeated = hourly_values.reindex(test.valid_time.dt.floor("h")).to_numpy()
            if not np.isfinite(repeated).all():
                raise RuntimeError(
                    "hourly reference lacks quarter-hour evaluation rows"
                )
            predictions = {
                "hourly_repeated": repeated,
                "interpolated_weather": model.predict(test),
            }
        for name, quantiles in predictions.items():
            context = test[["valid_time", "delivery_day", "cf", "capacity_mw"]].copy()
            context["daylight"] = (
                test.solar_elevation > solar.DAYLIGHT_ELEVATION
                if fuel == "solar"
                else True
            )
            for level, values in zip(levels, quantiles.T, strict=True):
                context[f"q{level:.2f}"] = values
            context["fold"] = origin
            collected.setdefault(name, []).append(context)

    rows, archives = [], []
    for name, frames in collected.items():
        context = pd.concat(frames, ignore_index=True)
        quantile_columns = [f"q{level:.2f}" for level in levels]
        daylight = context[context.daylight]
        values = daylight[quantile_columns].to_numpy()
        summary = metrics.summarise(daylight.cf.to_numpy(), values, levels)
        point = context["q0.50"].to_numpy()
        hourly = (
            context.assign(point=point)
            .set_index("valid_time")[["cf", "point"]]
            .resample("h")
            .mean()
            .dropna()
        )
        rows.append(
            {
                "name": name,
                "days": context.delivery_day.nunique(),
                "scored_intervals": len(daylight),
                **summary,
                "hourly_nmae": float((hourly.cf - hourly.point).abs().mean()),
                **ramp_scores(context, point),
            }
        )
        archives.append(context.assign(forecaster=name))
    if not rows:
        raise RuntimeError("no monthly evaluation folds")
    paths.PREDICTIONS.mkdir(parents=True, exist_ok=True)
    paths.INTERIM.mkdir(parents=True, exist_ok=True)
    pd.concat(archives, ignore_index=True).to_parquet(
        paths.PREDICTIONS / f"backtest_15min_{fuel}.parquet", index=False
    )
    table = pd.DataFrame(rows).sort_values("crps")
    table.to_parquet(paths.INTERIM / f"products_15min_{fuel}.parquet", index=False)
    # Same-row day-block intervals on paired CRPS differences; no headline gain is
    # claimed just because the point estimate is lower.
    import scoringrules as sr

    reference = "clear_sky_climatology" if fuel == "solar" else "hourly_repeated"
    reference_rows = pd.concat(collected[reference], ignore_index=True)
    reference_rows = reference_rows[reference_rows.daylight]
    reference_loss = sr.crps_quantile(
        reference_rows.cf.to_numpy(),
        reference_rows[[f"q{q:.2f}" for q in levels]].to_numpy(),
        levels,
    )
    intervals = []
    for name, frames in collected.items():
        context = pd.concat(frames, ignore_index=True)
        context = context[context.daylight]
        loss = sr.crps_quantile(
            context.cf.to_numpy(),
            context[[f"q{q:.2f}" for q in levels]].to_numpy(),
            levels,
        )
        low, high = splits.bootstrap_ci(
            pd.Series(loss - reference_loss), context.delivery_day
        )
        intervals.append(
            {"name": name, "crps_delta_ci_low": low, "crps_delta_ci_high": high}
        )
    table = table.merge(pd.DataFrame(intervals), on="name")
    table.to_parquet(paths.INTERIM / f"products_15min_{fuel}.parquet", index=False)
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fuel", choices=["wind_onshore", "solar"], required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print(run(args.fuel).round(5).to_string(index=False))


if __name__ == "__main__":
    main()
