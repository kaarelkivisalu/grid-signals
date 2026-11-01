"""Fixed load references: weekly naive, ridge and point/direct-quantile GBM."""

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from grid_signals.forecast.features.load import COLUMNS

LEVELS = np.arange(0.05, 1, 0.05).round(2)
PARAMS = {
    "n_estimators": 300,
    "num_leaves": 15,
    "learning_rate": 0.05,
    "min_child_samples": 80,
    "reg_lambda": 1.0,
    "n_jobs": 4,
    "random_state": 42,
    "verbose": -1,
}


class WeeklyNaive:
    def fit(self, frame: pd.DataFrame):
        self.offsets = np.quantile((frame.load - frame.load_lag_168).dropna(), LEVELS)
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.maximum(0, frame.load_lag_168.to_numpy()[:, None] + self.offsets)


class LinearLoad:
    def fit(self, frame: pd.DataFrame):
        self.model = make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            StandardScaler(),
            Ridge(alpha=10.0),
        ).fit(frame[COLUMNS], frame.load)
        return self

    def point(self, frame: pd.DataFrame) -> np.ndarray:
        return np.maximum(0, self.model.predict(frame[COLUMNS]))


class PointLoad:
    def fit(self, frame: pd.DataFrame):
        self.model = lgb.LGBMRegressor(objective="regression_l1", **PARAMS).fit(
            frame[COLUMNS], frame.load
        )
        return self

    def point(self, frame: pd.DataFrame) -> np.ndarray:
        return np.maximum(0, self.model.predict(frame[COLUMNS]))


class ResidualLoad:
    def __init__(self, factory) -> None:
        self.factory = factory

    def fit(self, frame: pd.DataFrame):
        days = sorted(frame.delivery_day.unique())
        if len(days) < 60:
            raise ValueError("load residual calibration needs at least 60 days")
        cutoff = days[-30]
        earlier, calibration = (
            frame[frame.delivery_day < cutoff],
            frame[frame.delivery_day >= cutoff],
        )
        model = self.factory().fit(earlier)
        self.offsets = np.quantile(
            calibration.load.to_numpy() - model.point(calibration), LEVELS
        )
        self.model = self.factory().fit(frame)
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.maximum(0, self.model.point(frame)[:, None] + self.offsets)


class QuantileLoad:
    def fit(self, frame: pd.DataFrame):
        self.models = [
            lgb.LGBMRegressor(objective="quantile", alpha=float(level), **PARAMS).fit(
                frame[COLUMNS], frame.load
            )
            for level in LEVELS
        ]
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        predictions = np.column_stack(
            [model.predict(frame[COLUMNS]) for model in self.models]
        )
        return np.maximum(0, np.sort(predictions, axis=1))


def factories() -> dict:
    return {
        "load_weekly": WeeklyNaive,
        "load_ridge": lambda: ResidualLoad(LinearLoad),
        "load_point_gbm": lambda: ResidualLoad(PointLoad),
        "load_quantile_gbm": QuantileLoad,
    }
