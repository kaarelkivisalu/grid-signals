"""Solar references, fitted on training days and evaluated on identical daylight rows."""

import numpy as np
import pandas as pd

from grid_signals.forecast.evaluation.splits import calibration_split


class ClearSkyClimatology:
    """Monthly clear-sky-index distribution, scaled by known solar geometry."""

    name = "clear_sky_climatology"

    def __init__(self, levels: np.ndarray) -> None:
        self.levels = levels
        self.months: dict[int, np.ndarray] = {}
        self.fallback = np.ones(len(levels))

    def fit(self, train: pd.DataFrame) -> "ClearSkyClimatology":
        usable = train[(train.solar_elevation > 5) & (train.clear_sky_cf > 0.02)].copy()
        usable["index"] = (usable.cf / usable.clear_sky_cf).clip(0, 2)
        self.fallback = np.quantile(usable["index"], self.levels)
        for month, rows in usable.groupby(usable.valid_time.dt.month):
            self.months[int(month)] = np.quantile(rows["index"], self.levels)
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        indices = np.vstack(
            [
                self.months.get(int(month), self.fallback)
                for month in frame.valid_time.dt.month
            ]
        )
        out = np.clip(indices * frame.clear_sky_cf.to_numpy()[:, None], 0, 1)
        out[frame.solar_elevation.to_numpy() <= 0] = 0
        return out


class SolarPhysical:
    """PV physics with one fitted derating factor and daylight-scaled residuals."""

    name = "solar_physical"

    def __init__(self, levels: np.ndarray) -> None:
        self.levels = levels
        self.scale = 1.0
        self.offsets = np.zeros(len(levels))

    def _point(self, frame: pd.DataFrame) -> np.ndarray:
        return np.clip(frame.physical_cf.to_numpy() * self.scale, 0, 1)

    def fit(self, train: pd.DataFrame) -> "SolarPhysical":
        train = train[train.solar_elevation > 5]
        inner, calibration = calibration_split(train)
        physical = inner.physical_cf.to_numpy()
        self.scale = float(
            np.clip(
                np.dot(physical, inner.cf) / max(np.dot(physical, physical), 1e-9),
                0.2,
                2,
            )
        )
        residuals = (calibration.cf.to_numpy() - self._point(calibration)) / np.maximum(
            calibration.clear_sky_cf.to_numpy(), 0.02
        )
        self.offsets = np.quantile(residuals, self.levels)
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        out = np.clip(
            self._point(frame)[:, None]
            + self.offsets * frame.clear_sky_cf.to_numpy()[:, None],
            0,
            1,
        )
        out[frame.solar_elevation.to_numpy() <= 0] = 0
        return out


class SmartPersistence(SolarPhysical):
    """48-hour observed clear-sky index; later actuals are never consulted."""

    name = "smart_persistence"

    def __init__(self, levels: np.ndarray, history: pd.DataFrame) -> None:
        super().__init__(levels)
        usable = history[history.clear_sky_cf > 0.02]
        self.history = (
            usable.set_index("valid_time").cf
            / usable.set_index("valid_time").clear_sky_cf
        ).clip(0, 2)
        self.fallback = 0.5

    def _point(self, frame: pd.DataFrame) -> np.ndarray:
        index = (
            self.history.reindex(frame.valid_time - pd.Timedelta(hours=48))
            .fillna(self.fallback)
            .to_numpy()
        )
        return np.clip(index * frame.clear_sky_cf.to_numpy(), 0, 1)

    def fit(self, train: pd.DataFrame) -> "SmartPersistence":
        usable = train[(train.solar_elevation > 5) & (train.clear_sky_cf > 0.02)]
        self.fallback = float((usable.cf / usable.clear_sky_cf).median())
        super().fit(train)
        return self
