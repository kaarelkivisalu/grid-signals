import importlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def predictions(namespace):
    quantile = importlib.import_module(namespace + ".models.quantile")
    solar = importlib.import_module(namespace + ".models.solar")
    load = importlib.import_module(namespace + ".models.load")
    price = importlib.import_module(namespace + ".models.price")
    metrics = importlib.import_module(namespace + ".evaluation.metrics")
    rng = np.random.default_rng(2184)
    n = 90 * 24
    frame = pd.DataFrame(
        {
            "delivery_day": np.repeat(pd.date_range("2025-01-01", periods=90), 24),
            "lead_hour": np.tile(np.arange(24) + 22, 90),
            "power_curve_model_mean": rng.uniform(0, 1, n),
            "solar_elevation": np.tile(np.sin(np.arange(24) * np.pi / 12) * 45, 90),
        }
    )
    frame["physical_cf"] = frame.power_curve_model_mean
    frame["cf"] = (frame.physical_cf * 0.8 + rng.normal(0, 0.08, n)).clip(0, 1)
    levels = np.array([0.1, 0.5, 0.9])
    params = {"n_estimators": 12, "n_jobs": 1, "random_state": 42}
    result = {}
    for name, factory in [
        ("wind", quantile.QuantileGBM),
        ("solar", solar.SolarQuantileGBM),
    ]:
        train, test = frame.iloc[:-48], frame.iloc[-48:]
        values = factory(levels, params=params).fit(train).predict(test)
        result[name] = {
            "predictions": values.tolist(),
            "metrics": metrics.summarise(test.cf.to_numpy(), values, levels),
        }
    frame = pd.DataFrame(rng.normal(size=(n, len(load.COLUMNS))), columns=load.COLUMNS)
    frame["delivery_day"] = np.repeat(pd.date_range("2025-01-01", periods=90), 24)
    frame["load"] = 50000 + frame.temperature * 1000 + rng.normal(0, 200, n)
    load.PARAMS = {**load.PARAMS, **params}
    values = load.QuantileLoad().fit(frame.iloc[:-48]).predict(frame.iloc[-48:])
    result["load"] = {
        "predictions": values.tolist(),
        "metrics": metrics.summarise(frame.load.to_numpy()[-48:], values, load.LEVELS),
    }
    times = pd.date_range("2025-01-01", periods=400 * 24, freq="h", tz="UTC")
    history = pd.Series(
        40 + 20 * np.sin(np.arange(len(times)) / 24) + rng.normal(0, 3, len(times)),
        index=times,
    )
    prices = importlib.import_module(namespace + ".sources.prices")
    frame = prices.features(history).dropna().reset_index(drop=True)
    train, test = frame.iloc[:-96], frame.iloc[-96:]
    for name, factory in [
        ("price_lear", lambda: price.ResidualDistribution(price.Lear)),
        ("price_quantile", price.QuantileGBM),
    ]:
        price.PARAMS = {**price.PARAMS, **params}
        values = factory().fit(train).predict(test)
        result[name] = {
            "predictions": values.tolist(),
            "metrics": metrics.summarise(test.price.to_numpy(), values, price.LEVELS),
        }
    return result


def test_fixed_input_predictions_and_scores_match_original(monkeypatch):
    for module in ("load", "price"):
        models = importlib.import_module("grid_signals.forecast.models." + module)
        monkeypatch.setattr(models, "PARAMS", models.PARAMS.copy())
    expected = json.loads(
        (
            Path(__file__).parent / "fixtures/pre_consolidation_predictions.json"
        ).read_text()
    )["results"]
    actual = predictions("grid_signals.forecast")
    for name, result in actual.items():
        np.testing.assert_allclose(
            result["predictions"],
            expected[name]["predictions"],
            rtol=1e-10,
            atol=1e-8,
            err_msg=name,
        )
        for key, value in result["metrics"].items():
            np.testing.assert_allclose(
                value,
                expected[name]["metrics"][key],
                rtol=1e-10,
                atol=1e-8,
                err_msg=f"{name} {key}",
            )
