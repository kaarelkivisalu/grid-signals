"""Daylight-only solar fitting with physical night-time bounds."""

import numpy as np
import pandas as pd

from grid_signals.forecast.models.quantile import QuantileGBM


class SolarQuantileGBM:
    """Learn the weather-to-PV correction on daylight; all night quantiles are zero."""

    name = "solar_quantile"

    def __init__(self, levels: np.ndarray, **kwargs) -> None:
        self.levels = levels
        self.inner = QuantileGBM(levels, **kwargs)

    def fit(self, train: pd.DataFrame) -> "SolarQuantileGBM":
        daylight = train[train.solar_elevation > 0].dropna(subset=["cf", "physical_cf"])
        if daylight.delivery_day.nunique() < 30:
            raise ValueError(
                "solar fitting needs at least 30 usable daylight delivery days"
            )
        self.inner.fit(daylight)
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        output = self.inner.predict(frame)
        output[frame.solar_elevation.to_numpy() <= 0] = 0.0
        return output
