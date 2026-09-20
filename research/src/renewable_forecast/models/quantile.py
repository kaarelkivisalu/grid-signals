"""Gradient-boosted quantile regression -- the v1 probabilistic model.

One booster per quantile level. No distributional assumption, physically bounded after
clipping, and it handles the pile-up of capacity factor at zero (wind lulls) without
special-casing. Quantiles are sorted afterwards so they cannot cross.
"""

import logging

import lightgbm as lgb
import numpy as np
import pandas as pd

from renewable_forecast.evaluation.splits import calibration_split
from renewable_forecast.models import base
from renewable_forecast.models.conformal import StratifiedCQR

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
    """LightGBM quantile regression across a set of levels.

    Optionally conformalised. Quantile regression fitted in-sample is systematically
    too narrow out of sample -- uncalibrated, this model returned 61% coverage at a
    nominal 80% -- so the conformal layer is on by default.
    """

    name = "lightgbm_quantile"

    def __init__(
        self,
        levels: np.ndarray,
        params: dict | None = None,
        *,
        conformalise: bool = True,
    ) -> None:
        self.levels = levels
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.conformalise = conformalise
        self.columns: list[str] = []
        self._models: list[lgb.LGBMRegressor] = []
        self._conformal: StratifiedCQR | None = None

    def fit(self, train: pd.DataFrame) -> "QuantileGBM":
        """Fit one booster per level, then calibrate on days it did not see."""
        inner, calib = calibration_split(train) if self.conformalise else (train, None)
        self.columns = base.feature_columns(train)
        features = base.matrix(inner, self.columns)
        target = inner.cf.to_numpy(dtype=float)

        # LightGBM refuses monotone constraints under the quantile objective, so the
        # constraint idea is exercised by PointGBM instead. The non-crossing repair and
        # the modest tree size carry the regularisation burden here.
        self._models = []
        for level in self.levels:
            model = lgb.LGBMRegressor(**self.params, alpha=float(level))
            model.fit(features, target)
            self._models.append(model)

        if self.conformalise and calib is not None and len(calib) > 200:
            self._conformal = StratifiedCQR(self.levels).fit(
                calib, self._raw_predict(calib)
            )
        return self

    def _raw_predict(self, frame: pd.DataFrame) -> np.ndarray:
        features = base.matrix(frame, self.columns)
        raw = np.column_stack([model.predict(features) for model in self._models])
        return np.sort(np.clip(raw, 0.0, 1.0), axis=1)

    def predict(self, test: pd.DataFrame) -> np.ndarray:
        """Predict every level, repair crossings, then apply the conformal correction.

        Quantile regressions are fitted independently and can cross; sorting is the
        standard non-crossing repair and preserves monotonicity.
        """
        raw = self._raw_predict(test)
        return self._conformal.apply(test, raw) if self._conformal else raw

    def importance(self) -> pd.DataFrame:
        """Gain-based importance of the median booster."""
        median = self._models[int(np.argmin(np.abs(self.levels - 0.5)))]
        return pd.DataFrame(
            {
                "feature": self.columns,
                "gain": median.booster_.feature_importance("gain"),
            }
        ).sort_values("gain", ascending=False)
