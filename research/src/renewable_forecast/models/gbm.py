"""Point gradient boosting with monotone constraints, dressed into quantiles.

The constraint is the point of this model: the fleet response must be non-decreasing in
the power-curve feature, and saying so explicitly is cheap insurance in the sparse
high-wind tail where ~745 training days give a tree almost nothing to learn from.
LightGBM cannot apply constraints under the quantile objective, so this is where the
idea gets tested.
"""

import lightgbm as lgb
import numpy as np
import pandas as pd

from renewable_forecast.models import base

DEFAULT_PARAMS = {
    # L1 would be more robust to the fat-tailed errors wind produces, but LightGBM
    # refuses monotone constraints under both `l1` and `quantile` -- only squared error
    # supports them. The constraint is the reason this model exists, so L2 it is, and
    # the robustness case is carried by the quantile model instead.
    "objective": "regression",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "n_estimators": 500,
    "min_child_samples": 40,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "verbose": -1,
}


class PointGBM:
    """Monotone-constrained point forecast, dressed with its empirical residuals."""

    name = "lightgbm_point_monotone"

    def __init__(self, levels: np.ndarray, params: dict | None = None) -> None:
        self.levels = levels
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.columns: list[str] = []
        self._model: lgb.LGBMRegressor | None = None
        self._offsets = np.zeros(len(levels))

    def fit(self, train: pd.DataFrame) -> "PointGBM":
        """Fit the constrained booster and the residual quantiles."""
        self.columns = base.feature_columns(train)
        features = base.matrix(train, self.columns)
        target = train.cf.to_numpy(dtype=float)
        self._model = lgb.LGBMRegressor(
            **self.params,
            monotone_constraints=base.monotone_constraints(self.columns),
        )
        self._model.fit(features, target)
        self._offsets = np.quantile(target - self._model.predict(features), self.levels)
        return self

    def predict(self, test: pd.DataFrame) -> np.ndarray:
        """Point prediction dressed into quantiles."""
        point = self._model.predict(base.matrix(test, self.columns))
        return np.clip(point[:, None] + self._offsets[None, :], 0.0, 1.0)
