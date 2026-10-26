"""Price-only seasonal, LEAR and GBM references; negative prices remain valid."""

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LassoLarsIC

LEVELS = np.arange(0.05, 1, 0.05).round(2)
PARAMS = {
    "n_estimators": 300,
    "num_leaves": 15,
    "learning_rate": 0.05,
    "min_child_samples": 60,
    "reg_lambda": 1.0,
    "n_jobs": 4,
    "random_state": 42,
    "verbose": -1,
}


class SeasonalNaive:
    name = "seasonal_naive"

    def fit(self, train: pd.DataFrame):
        residual = train.price - train.p_lag_168
        self.offsets = np.quantile(residual.dropna(), LEVELS)
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return frame.p_lag_168.to_numpy()[:, None] + self.offsets


class Lear:
    """Hourly price-only LEAR adaptation: four daily lag profiles and weekday dummies."""

    name = "lear_hourly"

    def fit(self, train: pd.DataFrame):
        self.columns = [
            column for column in train if column.startswith(("profile_", "dow_"))
        ]
        daily = train.groupby("delivery_day")[self.columns].first()
        targets = (
            train.groupby(["delivery_day", "local_hour"])
            .price.mean()
            .unstack()
            .reindex(columns=range(24))
        )
        complete = targets.notna().all(axis=1)
        targets = targets[complete]
        daily = daily.reindex(targets.index)
        self.imputer = SimpleImputer(strategy="median", keep_empty_features=True).fit(
            daily
        )
        x = self.imputer.transform(daily)
        self.location = np.median(x, axis=0)
        self.scale = np.median(np.abs(x - self.location), axis=0)
        self.scale[self.scale < 1e-8] = 1
        x = np.arcsinh((x - self.location) / self.scale)
        y = targets.to_numpy()
        self.target_location = np.median(y, axis=0)
        self.target_scale = np.median(np.abs(y - self.target_location), axis=0)
        self.target_scale[self.target_scale < 1e-8] = 1
        y = np.arcsinh((y - self.target_location) / self.target_scale)
        self.models = [
            LassoLarsIC(criterion="aic", max_iter=500).fit(x, y[:, hour])
            for hour in range(24)
        ]
        # Residual quantiles are fitted on an earlier calibration window, never test prices.
        return self

    def point(self, frame: pd.DataFrame) -> np.ndarray:
        x = self.imputer.transform(frame[self.columns])
        x = np.arcsinh((x - self.location) / self.scale)
        output = np.zeros(len(frame))
        for hour, model in enumerate(self.models):
            mask = frame.local_hour.to_numpy() == hour
            if mask.any():
                output[mask] = (
                    np.sinh(model.predict(x[mask])) * self.target_scale[hour]
                    + self.target_location[hour]
                )
        return output


class PointGBM:
    name = "lightgbm_point"

    def fit(self, train: pd.DataFrame):
        self.columns = [
            column
            for column in train
            if column.startswith(("p_lag_", "profile_", "dow_"))
            or column in {"quarter", "month"}
        ]
        self.model = lgb.LGBMRegressor(objective="regression_l1", **PARAMS).fit(
            train[self.columns], train.price
        )
        return self

    def point(self, frame: pd.DataFrame) -> np.ndarray:
        return self.model.predict(frame[self.columns])


class ResidualDistribution:
    """Estimate uncertainty out of sample, then refit the point model on all training days."""

    def __init__(self, factory) -> None:
        self.factory = factory

    def fit(self, train: pd.DataFrame):
        days = sorted(train.delivery_day.unique())
        cutoff = days[-30]
        inner, calibration = (
            train[train.delivery_day < cutoff],
            train[train.delivery_day >= cutoff],
        )
        model = self.factory().fit(inner)
        residual = calibration.price.to_numpy() - model.point(calibration)
        self.offsets = np.quantile(residual, LEVELS)
        self.model = self.factory().fit(train)
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.model.point(frame)[:, None] + self.offsets


class QuantileGBM(PointGBM):
    name = "lightgbm_quantile"

    def fit(self, train: pd.DataFrame):
        self.columns = [
            column
            for column in train
            if column.startswith(("p_lag_", "profile_", "dow_"))
            or column in {"quarter", "month"}
        ]
        self.models = [
            lgb.LGBMRegressor(objective="quantile", alpha=float(level), **PARAMS).fit(
                train[self.columns], train.price
            )
            for level in LEVELS
        ]
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.sort(
            np.column_stack(
                [model.predict(frame[self.columns]) for model in self.models]
            ),
            axis=1,
        )
