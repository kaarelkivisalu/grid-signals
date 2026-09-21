"""Fit and score every forecaster -- baselines and models -- on the frozen protocol."""

import logging

import numpy as np
import pandas as pd

from renewable_forecast import config
from renewable_forecast.evaluation import baselines
from renewable_forecast.models.gbm import PointGBM
from renewable_forecast.models.quantile import QuantileGBM
from renewable_forecast.models.sanity import RidgeSanityFloor
from renewable_forecast.pipelines import evaluate

logger = logging.getLogger(__name__)

#: The ridge floor must beat climatology decisively. If it does not, the fault is in the
#: pipeline, not the model, and nothing downstream is worth running.
SANITY_MARGIN = 0.10


def forecasters(levels: np.ndarray, history: pd.Series, tso_cf: pd.Series) -> dict:
    """Every forecaster on the board, as zero-argument factories."""
    return {
        "climatology": lambda: _Adapter(baselines.Climatology(levels)),
        "persistence": lambda: _Adapter(baselines.Persistence(levels), history),
        baselines.TsoForecast.name: lambda: _Adapter(
            baselines.TsoForecast(levels), tso_cf
        ),
        baselines.PhysicalPowerCurve.name: lambda: _Adapter(
            baselines.PhysicalPowerCurve(levels)
        ),
        RidgeSanityFloor.name: lambda: _Adapter(RidgeSanityFloor(levels)),
        PointGBM.name: lambda: _Adapter(PointGBM(levels)),
        QuantileGBM.name: lambda: _Adapter(QuantileGBM(levels)),
    }


class _Adapter:
    """Give every forecaster the same fit/predict signature.

    Some baselines need an extra series (the history, the published forecast); the
    models do not. Normalising here keeps the scoring loop free of special cases.
    """

    def __init__(self, inner, extra: pd.Series | None = None) -> None:
        self.inner = inner
        self.extra = extra

    def fit(self, train: pd.DataFrame) -> "_Adapter":
        """Fit the wrapped forecaster."""
        if self.extra is None:
            self.inner.fit(train)
        else:
            self.inner.fit(train, self.extra)
        return self

    def predict(self, test: pd.DataFrame) -> np.ndarray:
        """Predict quantiles from the wrapped forecaster."""
        if self.extra is None:
            return self.inner.predict(test)
        return self.inner.predict(test, self.extra)


def run(zone: str = "SE3", fuel: str = "wind_onshore") -> pd.DataFrame:
    """Score every forecaster on the development set."""
    cfg = config.load()
    levels = np.array(cfg.task.quantiles)

    frame = evaluate.load_design_matrix(zone, fuel)
    development, _ = evaluate.development_split(frame, cfg)

    history = frame.set_index("valid_time").cf
    tso_mw = baselines.TsoForecast.load(zone, fuel)
    tso_cf = (tso_mw / frame.set_index("valid_time").capacity_mw).dropna()

    actual, context, predictions = evaluate.run_folds(
        frame, development, forecasters(levels, history, tso_cf), cfg
    )
    evaluate.save_predictions(context, predictions, levels, zone, fuel)
    rows = [
        evaluate.score(
            name,
            actual,
            quantiles,
            levels,
            context,
            cfg,
            kind="model" if "lightgbm" in name or "ridge" in name else "baseline",
        )
        for name, quantiles in predictions.items()
    ]
    return evaluate.leaderboard(rows, actual, predictions, levels, context)


def check_sanity_floor(table: pd.DataFrame) -> None:
    """Refuse to trust the board if the linear floor cannot beat climatology."""
    scores = table.set_index("name").crps
    floor, climatology = scores.get(RidgeSanityFloor.name), scores.get("climatology")
    if floor is None or climatology is None:
        return
    improvement = 1 - floor / climatology
    if improvement < SANITY_MARGIN:
        logger.error(
            "SANITY FLOOR FAILED: ridge improves CRPS by only %.1f%% over climatology. "
            "Suspect the pipeline, not the model.",
            100 * improvement,
        )
    else:
        logger.info(
            "sanity floor ok: ridge beats climatology by %.1f%%", 100 * improvement
        )


def main() -> int:
    """Score everything and print the leaderboard."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    table = run()
    check_sanity_floor(table)
    print(table.round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
