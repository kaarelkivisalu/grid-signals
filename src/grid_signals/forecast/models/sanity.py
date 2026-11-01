"""The sanity floor.

A ridge regression on a handful of physical features. If this does not beat climatology
decisively, the problem is a pipeline bug, not a modelling one -- and no amount of
gradient boosting will fix it. Nothing downstream runs until this passes.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from grid_signals.forecast.evaluation.splits import calibration_split

PHYSICS_FEATURES = (
    "power_curve_model_mean",
    "wind_speed_100m_model_mean",
    "power_curve_model_std",
    "hour_sin",
    "hour_cos",
    "doy_sin",
    "doy_cos",
    "lead_hour",
)


class RidgeSanityFloor:
    """Linear model on physics plus calendar, dressed with its own residuals."""

    name = "ridge_sanity_floor"

    def __init__(self, levels: np.ndarray) -> None:
        self.levels = levels
        self.columns: list[str] = []
        self._model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        self._offsets = np.zeros(len(levels))

    def _matrix(self, frame: pd.DataFrame) -> np.ndarray:
        values = frame[self.columns].to_numpy(dtype=float)
        return np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)

    def fit(self, train: pd.DataFrame) -> "RidgeSanityFloor":
        """Fit the linear model and the empirical residual quantiles."""
        inner, calib = calibration_split(train)
        self.columns = [c for c in PHYSICS_FEATURES if c in train.columns]
        self._model.fit(self._matrix(inner), inner.cf.to_numpy(dtype=float))
        # Residuals must come from days the model did not fit, or the intervals inherit
        # the in-sample spread and come out far too narrow.
        residuals = calib.cf.to_numpy(dtype=float) - self._model.predict(
            self._matrix(calib)
        )
        self._offsets = np.quantile(residuals, self.levels)
        return self

    def predict(self, test: pd.DataFrame) -> np.ndarray:
        """Point prediction dressed into quantiles by the residual distribution."""
        point = self._model.predict(self._matrix(test))
        return np.clip(point[:, None] + self._offsets[None, :], 0.0, 1.0)
