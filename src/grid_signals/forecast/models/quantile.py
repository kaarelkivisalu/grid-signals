"""Gradient-boosted quantile regression -- the v1 probabilistic model.

One booster per quantile level. No distributional assumption, physically bounded after
clipping, and it handles the pile-up of capacity factor at zero (wind lulls) without
special-casing. Quantiles are sorted afterwards so they cannot cross.
"""

import logging

import lightgbm as lgb
import numpy as np
import pandas as pd

from grid_signals.forecast.evaluation import splits
from grid_signals.forecast.evaluation.splits import calibration_split
from grid_signals.forecast.models import base
from grid_signals.forecast.models.conformal import SpreadCQR

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
        calibration: str = "recent",
        by_season: bool = False,
        n_blocks: int = 4,
    ) -> None:
        self.levels = levels
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.conformalise = conformalise
        if calibration not in {"recent", "crossfit"}:
            msg = f"unknown calibration scheme {calibration}"
            raise ValueError(msg)
        self.calibration = calibration
        self.by_season = by_season
        self.n_blocks = n_blocks
        self.columns: list[str] = []
        self._models: list[lgb.LGBMRegressor] = []
        self._conformal: SpreadCQR | None = None

    def _fit_boosters(self, frame: pd.DataFrame) -> list[lgb.LGBMRegressor]:
        # LightGBM refuses monotone constraints under the quantile objective, so the
        # constraint idea is exercised by PointGBM instead. The non-crossing repair and
        # the modest tree size carry the regularisation burden here.
        features = base.matrix(frame, self.columns)
        target = frame.cf.to_numpy(dtype=float)
        models = []
        for level in self.levels:
            model = lgb.LGBMRegressor(**self.params, alpha=float(level))
            model.fit(features, target)
            models.append(model)
        return models

    def _calibrator(self) -> SpreadCQR:
        # Additive, level x NWP-spread strata: same CRPS as the lead x level layer it
        # replaced, with 80% coverage 0.737 -> 0.774 and flat across spread quartiles
        # (`reports/calibration.md`, `pipelines/compare_calibration.py`).
        return SpreadCQR(self.levels, normalise=False, by_season=self.by_season)

    def fit(self, train: pd.DataFrame) -> "QuantileGBM":
        """Fit one booster per level, then calibrate on days it did not see.

        `calibration="recent"` holds out the most recent quarter of the window, fits on
        the rest, and calibrates on the holdout. `"crossfit"` fits on each of
        `n_blocks` contiguous day-blocks' complement, calibrates on the pooled
        out-of-fold predictions -- which span every season in the window -- and then
        refits on the whole window.
        """
        self.columns = base.feature_columns(train)
        if not self.conformalise:
            self._models = self._fit_boosters(train)
            return self

        if self.calibration == "recent":
            inner, calib = calibration_split(train)
            self._models = self._fit_boosters(inner)
            if len(calib) > 200:
                self._conformal = self._calibrator().fit(
                    calib, self._raw_predict(calib)
                )
            return self

        train = train.reset_index(drop=True)
        out_of_fold = np.empty((len(train), len(self.levels)))
        for block in splits.day_blocks(train, self.n_blocks):
            self._models = self._fit_boosters(train.drop(index=block))
            out_of_fold[block] = self._raw_predict(train.loc[block])
        self._conformal = self._calibrator().fit(train, out_of_fold)
        self._models = self._fit_boosters(train)
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
