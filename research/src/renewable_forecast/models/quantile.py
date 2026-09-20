"""Gradient-boosted quantile regression -- the v1 probabilistic model.

One booster per quantile level. No distributional assumption, physically bounded after
clipping, and it handles the pile-up of capacity factor at zero (wind lulls) without
special-casing. Quantiles are sorted afterwards so they cannot cross.
"""

import logging

import lightgbm as lgb
import numpy as np
import pandas as pd

from renewable_forecast.models import base

logger = logging.getLogger(__name__)

#: Deliberately small. With roughly 745 effective training days, a deep forest memorises.
DEFAULT_PARAMS = {
    "objective": "quantile",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "n_estimators": 400,
    "min_child_samples": 40,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "verbose": -1,
}


class QuantileGBM:
    """LightGBM quantile regression across a set of levels."""

    name = "lightgbm_quantile"

    def __init__(self, levels: np.ndarray, params: dict | None = None) -> None:
        self.levels = levels
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.columns: list[str] = []
        self._models: list[lgb.LGBMRegressor] = []

    def fit(self, train: pd.DataFrame) -> "QuantileGBM":
        """Fit one booster per quantile level."""
        self.columns = base.feature_columns(train)
        features = base.matrix(train, self.columns)
        target = train.cf.to_numpy(dtype=float)
        constraints = base.monotone_constraints(self.columns)

        self._models = []
        for level in self.levels:
            model = lgb.LGBMRegressor(
                **self.params, alpha=float(level), monotone_constraints=constraints
            )
            model.fit(features, target)
            self._models.append(model)
        return self

    def predict(self, test: pd.DataFrame) -> np.ndarray:
        """Predict every level, then repair crossings by sorting."""
        features = base.matrix(test, self.columns)
        raw = np.column_stack([model.predict(features) for model in self._models])
        # Quantile regressions are fitted independently and can cross; sorting is the
        # standard non-crossing repair and is monotone-preserving.
        return np.sort(np.clip(raw, 0.0, 1.0), axis=1)

    def importance(self) -> pd.DataFrame:
        """Gain-based importance of the median booster."""
        median = self._models[int(np.argmin(np.abs(self.levels - 0.5)))]
        return pd.DataFrame(
            {
                "feature": self.columns,
                "gain": median.booster_.feature_importance("gain"),
            }
        ).sort_values("gain", ascending=False)
