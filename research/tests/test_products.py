"""Quarter-hour products: real observations, safe interpolation and task isolation."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from grid_signals.forecast import config, windows
from grid_signals.forecast.evaluation.solar import (
    ClearSkyClimatology,
    SmartPersistence,
    SolarPhysical,
)
from grid_signals.forecast.features import assemble, resolution, solar
from grid_signals.forecast.models.solar import SolarQuantileGBM
from grid_signals.forecast.pipelines import backtest_products, evaluate, predict
from grid_signals.forecast.targets import actuals


def test_weather_interpolation_preserves_missing_values_gaps_and_vintages():
    sample = pd.DataFrame(
        {
            "valid_time": pd.to_datetime(
                [
                    "2026-01-01T00:00Z",
                    "2026-01-01T01:00Z",
                    "2026-01-01T03:00Z",
                    "2026-01-01T04:00Z",
                ]
            ),
            "run_time": pd.Timestamp("2025-12-31", tz="UTC"),
            "point_id": "a",
            "speed": [2.0, 6.0, np.nan, 10.0],
            "wind_direction": [350.0, 10.0, 20.0, 30.0],
        }
    )
    second = sample.assign(run_time=pd.Timestamp("2025-12-30", tz="UTC"), speed=20.0)
    output = resolution.interpolate(pd.concat([sample, second]))
    first = output[output.run_time == sample.run_time.iloc[0]].set_index("valid_time")
    assert first.speed.iloc[:5].tolist() == [2, 3, 4, 5, 6]
    assert first.wind_direction.iloc[2] == pytest.approx(0)
    assert first.speed.iloc[5:-1].isna().all(), (
        "missing endpoints and multi-hour gaps must survive"
    )
    assert len(output) == 34, "vintages must not collapse into one series"
    assert output[output.run_time == second.run_time.iloc[0]].speed.iloc[1] == 20


def test_wind_interpolates_speed_before_the_nonlinear_power_curve():
    times = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    sample = pd.DataFrame({"valid_time": times, "point_id": "a", "model": "first"})
    for variable, values in {
        "wind_speed_100m": [0.0, 14.0],
        "wind_speed_10m": [0.0, 10.0],
        "wind_direction_100m": [0.0, 0.0],
        "wind_gusts_10m": [0.0, 15.0],
        "temperature_2m": [20.0, 20.0],
        "surface_pressure": [1013.25, 1013.25],
        "relative_humidity_2m": [50.0, 50.0],
        "snow_depth": [0.0, 0.0],
    }.items():
        sample[f"{variable}_previous_day1"] = values
    raw = pd.concat([sample, sample.assign(model="second")], ignore_index=True)
    points = pd.DataFrame({"point_id": ["a"], "weight": [1.0]})
    frame = assemble._features_at(raw, points, 1, "15min")  # noqa: SLF001
    midpoint = frame[frame.valid_time == times[0] + pd.Timedelta("30min")].iloc[0]
    assert midpoint.wind_speed_100m_model_mean == pytest.approx(7.0)
    assert 0.25 < midpoint.power_curve_model_mean < 0.35
    assert frame.power_curve_model_mean.iloc[-1] == pytest.approx(1.0)


def test_quarter_hour_targets_never_expand_hourly_measurements():
    times = pd.to_datetime(
        [
            "2026-01-01T00:00Z",
            "2026-01-01T01:00Z",
            "2026-01-01T01:15Z",
            "2026-01-01T01:30Z",
            "2026-01-01T01:45Z",
            "2026-01-01T02:00Z",
            "2026-01-01T02:15Z",
        ]
    )
    raw = pd.DataFrame(
        {
            "period_start": times,
            "fuel_type": "Wind Onshore",
            "zone": "SE3",
            "value_mw": np.arange(7),
            "fetched_at": pd.Timestamp("2026-01-02", tz="UTC"),
        }
    )
    out = actuals.to_quarter_hourly(raw)
    assert out.mw.tolist() == [1, 2, 3, 4]
    assert out.period_start.dt.hour.unique().tolist() == [1]


@pytest.mark.parametrize(
    ("day", "count"),
    [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100), (date(2026, 1, 1), 96)],
)
def test_quarter_hour_delivery_days_follow_dst(day, count):
    starts = windows.delivery_day_starts(day, resolution=pd.Timedelta("15min"))
    assert len(starts) == len(set(starts)) == count
    assert (pd.Series(starts).diff().dropna() == pd.Timedelta("15min")).all()


def test_non_positive_resolution_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        windows.delivery_day_starts(date(2026, 1, 1), resolution=pd.Timedelta(0))


def test_quarter_hour_offsets_cover_the_interpolation_and_trajectory_endpoint():
    frame = pd.DataFrame(
        {"valid_time": pd.date_range("2026-01-02T23:00Z", periods=96, freq="15min")}
    )
    frame = assemble._annotate(frame)  # noqa: SLF001
    latest_input = frame.valid_time.dt.ceil("h") + pd.Timedelta(hours=3)
    assert (
        latest_input - pd.to_timedelta(frame.nwp_offset_days * 24, unit="h")
        <= assemble.issue_time_of(frame)
    ).all()


def test_solar_capacity_uses_no_future_snapshot(monkeypatch):
    snapshots = pd.Series(
        [100.0, 200.0], index=pd.to_datetime(["2025-01-01T00:00Z", "2026-01-01T00:00Z"])
    )
    monkeypatch.setattr(solar, "capacity_snapshots", lambda: snapshots)
    assert solar.capacity_at(
        pd.Series(pd.to_datetime(["2025-07-01T09:00Z", "2026-07-01T09:00Z"]))
    ).tolist() == [100, 200]
    with pytest.raises(ValueError, match="known"):
        solar.capacity_at(pd.Series(pd.to_datetime(["2024-01-01T09:00Z"])))


def test_pv_physics_has_daylight_output_and_zero_night():
    times = pd.date_range("2026-06-01", periods=24, freq="h", tz="UTC")
    output, elevation = solar.pv_output(
        np.full(24, 600.0), np.full(24, 20.0), times, 51.0, 10.0
    )
    assert (output[elevation <= 0] == 0).all()
    assert output[elevation > 5].mean() > 0.1
    assert np.isfinite(output).all()
    assert ((output >= 0) & (output <= 1)).all()


def test_solar_model_keeps_night_zero_after_calibration():
    times = pd.date_range("2025-01-01", periods=40 * 24, freq="h", tz="UTC")
    is_day = (times.hour >= 8) & (times.hour <= 16)
    frame = pd.DataFrame(
        {
            "valid_time": times,
            "delivery_day": times.tz_localize(None).normalize(),
            "solar_elevation": np.where(is_day, 20, -20),
            "physical_cf": np.where(is_day, 0.3, 0.0),
            "clear_sky_cf": np.where(is_day, 0.5, 0),
            "cf": np.where(is_day, 0.2, 0),
        }
    )
    levels = np.array([0.1, 0.5, 0.9])
    model = SolarQuantileGBM(levels, params={"n_estimators": 5, "n_jobs": 1}).fit(frame)
    output = model.predict(frame)
    assert model.predict(frame.drop(columns="cf")) == pytest.approx(output)
    assert output.shape == (len(frame), 3)
    assert (output[~is_day] == 0).all()
    assert (np.diff(output, axis=1) >= 0).all()


@pytest.mark.parametrize(
    "reference", [ClearSkyClimatology, SolarPhysical, SmartPersistence]
)
def test_solar_references_do_not_need_test_actuals(reference):
    times = pd.date_range("2025-01-01", periods=40 * 24, freq="h", tz="UTC")
    daylight = (times.hour >= 8) & (times.hour <= 16)
    frame = pd.DataFrame(
        {
            "valid_time": times,
            "delivery_day": times.tz_localize(None).normalize(),
            "solar_elevation": np.where(daylight, 20, -20),
            "physical_cf": np.where(daylight, 0.3, 0.0),
            "clear_sky_cf": np.where(daylight, 0.5, 0.0),
            "cf": np.where(daylight, 0.2, 0.0),
        }
    )
    levels = np.array([0.1, 0.5, 0.9])
    model = (
        reference(levels, frame) if reference is SmartPersistence else reference(levels)
    )
    model.fit(frame)
    expected = model.predict(frame)
    assert model.predict(frame.drop(columns="cf")) == pytest.approx(expected)
    assert (expected[~daylight] == 0).all()


def test_latest_forecast_filters_zone_fuel_resolution_and_legacy(monkeypatch, tmp_path):
    archive = tmp_path / "vintages.parquet"
    monkeypatch.setattr(predict, "VINTAGES", archive)
    legacy = pd.DataFrame(
        {
            "valid_time": pd.to_datetime(["2026-01-01T00:00Z"]),
            "created_at": pd.to_datetime(["2025-12-31T09:00Z"]),
        }
    )
    legacy.to_parquet(archive, index=False)
    assert predict.latest("SE3").resolution.tolist() == ["1h"]
    wind = predict._read_vintages()  # noqa: SLF001
    new = legacy.assign(
        zone="DE_LU",
        fuel_type="solar",
        resolution="15min",
        created_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )
    pd.concat([wind, new]).to_parquet(archive, index=False)
    assert predict.latest("SE3").created_at.iloc[0] == legacy.created_at.iloc[0]
    assert predict.latest("DE_LU", "solar", "15min").zone.tolist() == ["DE_LU"]
    with pytest.raises(FileNotFoundError):
        predict.latest("SE3", resolution="15min")


@pytest.mark.parametrize(
    ("method", "source_resolution"), [("interpolate", "15min"), ("repeat", "1h")]
)
def test_predict_respects_issue_cutoff_and_returns_only_the_new_vintage(
    monkeypatch, tmp_path, method, source_resolution
):
    archive = tmp_path / "vintages.parquet"
    monkeypatch.setattr(predict, "VINTAGES", archive)
    from grid_signals.forecast import versions

    monkeypatch.setattr(versions, "verify", lambda: {"identity": "fixture-version"})
    future = pd.DataFrame(
        {
            "valid_time": pd.to_datetime(
                windows.delivery_day_starts(
                    date(2026, 1, 3), resolution=pd.Timedelta("15min")
                ),
                utc=True,
            ),
            "delivery_day": pd.Timestamp("2026-01-03"),
            "lead_hour": 30,
            "capacity_mw": 1000.0,
            "power_curve_model_mean": 0.2,
            "power_curve__meps": 0.2,
            "power_curve__ifsrun": 0.2,
        }
    )
    training = pd.DataFrame(
        {
            "delivery_day": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "cf": 0.2,
        }
    )
    fitted = []
    resolutions = []

    def build_future(*args, resolution, **kwargs):  # noqa: ARG001
        resolutions.append(resolution)
        return (
            future[future.valid_time.dt.minute == 0] if resolution == "1h" else future
        )

    class Model:
        def __init__(self, levels, **kwargs) -> None:  # noqa: ARG002
            self.levels = levels

        def fit(self, frame):
            fitted.append(frame.copy())
            return self

        def predict(self, frame):
            return np.full((len(frame), len(self.levels)), 0.2)

    monkeypatch.setattr(predict.assemble, "build", lambda *_args, **_kwargs: training)
    monkeypatch.setattr(predict.assemble, "build_operational", build_future)
    monkeypatch.setattr(predict, "QuantileGBM", Model)
    first = predict._fit_forecast(date(2026, 1, 3), refresh=False, wind_method=method)  # noqa: SLF001 -- original fitting regression
    second = predict._fit_forecast(date(2026, 1, 3), refresh=False, wind_method=method)  # noqa: SLF001 -- original fitting regression
    assert len(first) == len(second) == 96
    assert len(pd.read_parquet(archive)) == 192
    assert resolutions == [source_resolution, source_resolution]
    assert fitted[0].delivery_day.tolist() == [pd.Timestamp("2026-01-01")]
    assert ((second.period_end - second.valid_time) == pd.Timedelta("15min")).all()
    assert second["mw_q0.50"].tolist() == [200.0] * 96


def test_product_evaluation_refuses_the_sealed_holdout():
    with pytest.raises(ValueError, match="sealed"):
        backtest_products.run("solar", end=date(2026, 3, 21))


def test_refreshing_actuals_cannot_move_the_frozen_holdout():
    frame = pd.DataFrame({"delivery_day": pd.date_range("2024-01-01", "2026-10-15")})
    development, holdout = evaluate.development_split(frame, config.load())
    assert development.max() == pd.Timestamp("2026-03-19")
    assert holdout.min() == pd.Timestamp("2026-03-20")
    assert holdout.max() == pd.Timestamp("2026-09-19")


def test_complete_days_rejects_missing_intervals_and_weather():
    times = pd.date_range("2026-01-01T23:00Z", periods=96, freq="15min")
    frame = pd.DataFrame(
        {"valid_time": times, "delivery_day": pd.Timestamp("2026-01-02"), "cf": 0.2}
    )
    assert len(backtest_products.complete_days(frame, ["cf"])) == 96
    assert backtest_products.complete_days(frame.iloc[:-1], ["cf"]).empty
    frame.loc[2, "cf"] = np.nan
    assert backtest_products.complete_days(frame, ["cf"]).empty


def test_ramp_scores_do_not_compare_different_delivery_days():
    times = pd.to_datetime(
        [
            "2026-01-01T00:00Z",
            "2026-01-01T00:15Z",
            "2026-01-02T00:00Z",
            "2026-01-02T00:15Z",
        ]
    )
    frame = pd.DataFrame(
        {
            "valid_time": times,
            "delivery_day": times.tz_localize(None).normalize(),
            "cf": [0.0, 0.1, 0.9, 1.0],
        }
    )
    scores = backtest_products.ramp_scores(frame, np.array([0.0, 0.0, 0.0, 0.0]))
    assert scores["ramp_mae_cf"] == pytest.approx(0.1)
