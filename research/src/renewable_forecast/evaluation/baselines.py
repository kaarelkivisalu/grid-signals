"""Reference forecasts. These go on the leaderboard before any model is fitted.

Each baseline emits a full predictive distribution, not a point, so that CRPS is
comparable across everything on the board. Point-only references (persistence, the TSO
forecast) are dressed with their own empirical error distribution, fitted on training
data only.
"""

import numpy as np
import pandas as pd

from renewable_forecast.sources import entsoe
from renewable_forecast.targets import actuals

#: The forecast is issued at 09:00 UTC on day D for delivery on D+1, so the freshest
#: usable actual is the end of D-1 -- roughly 48 hours before the target hour.
PERSISTENCE_LAG_HOURS = 48


def _dress(point: np.ndarray, residuals: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """Turn a point forecast into quantiles using an empirical error distribution."""
    offsets = np.quantile(residuals[~np.isnan(residuals)], levels)
    return np.clip(point[:, None] + offsets[None, :], 0.0, 1.0)


class Climatology:
    """Empirical capacity-factor quantiles conditioned on month and hour of day.

    This is the CRPS denominator: a model that cannot beat it has learned nothing.
    """

    def __init__(self, levels: np.ndarray) -> None:
        self.levels = levels
        self._table: dict[tuple[int, int], np.ndarray] = {}
        self._fallback: np.ndarray = np.zeros(len(levels))

    def fit(self, train: pd.DataFrame) -> "Climatology":
        """Tabulate quantiles per (month, hour) from training data only."""
        self._fallback = np.quantile(train.cf.dropna(), self.levels)
        for key, group in train.groupby(
            [
                train.period_start.dt.month,
                train.period_start.dt.hour,
            ]
        ):
            values = group.cf.dropna()
            if len(values) >= 30:
                self._table[key] = np.quantile(values, self.levels)
        return self

    def predict(self, test: pd.DataFrame) -> np.ndarray:
        """Look up the quantiles for each target hour."""
        keys = zip(test.period_start.dt.month, test.period_start.dt.hour, strict=True)
        return np.vstack([self._table.get(k, self._fallback) for k in keys])


class Persistence:
    """Yesterday's capacity factor at the same hour, dressed with its own errors."""

    def __init__(self, levels: np.ndarray) -> None:
        self.levels = levels
        self._residuals = np.array([0.0])

    @staticmethod
    def _lagged(frame: pd.DataFrame, history: pd.Series) -> np.ndarray:
        lagged_index = frame.period_start - pd.Timedelta(hours=PERSISTENCE_LAG_HOURS)
        return history.reindex(lagged_index).to_numpy()

    def fit(self, train: pd.DataFrame, history: pd.Series) -> "Persistence":
        """Learn the empirical distribution of 48-hour persistence errors."""
        point = self._lagged(train, history)
        self._residuals = train.cf.to_numpy() - point
        return self

    def predict(self, test: pd.DataFrame, history: pd.Series) -> np.ndarray:
        """Dress the lagged actual with the fitted error distribution."""
        point = np.nan_to_num(
            self._lagged(test, history), nan=float(np.nanmean(history))
        )
        return _dress(point, self._residuals, self.levels)


class TsoForecast:
    """ENTSO-E A69, the published day-ahead wind and solar forecast.

    Recorded as `A69_latest_vintage`: the Transparency Platform serves the latest
    revision for a target time and exposes no publication timestamp, so this benchmark
    may embed information that was not available at gate closure. It is therefore
    **optimistic**, and every comparison against it must carry that caveat.
    """

    name = "A69_latest_vintage"

    def __init__(self, levels: np.ndarray) -> None:
        self.levels = levels
        self._residuals = np.array([0.0])

    @staticmethod
    def load(zone: str, fuel: str) -> pd.Series:
        """Published forecast MW on the hourly UTC grid."""
        raw = entsoe.load("da_wind_solar_forecast", zone)
        if raw.empty:
            return pd.Series(dtype="float64")
        raw["fuel_type"] = raw.fuel_type.map(actuals.slug)
        hourly = actuals.to_hourly(raw)
        hourly = hourly[hourly.fuel_type == fuel]
        return hourly.set_index("period_start").mw.rename("forecast_mw")

    def fit(self, train: pd.DataFrame, forecast_cf: pd.Series) -> "TsoForecast":
        """Learn the published forecast's own error distribution."""
        point = forecast_cf.reindex(train.period_start).to_numpy()
        self._residuals = train.cf.to_numpy() - point
        return self

    def predict(self, test: pd.DataFrame, forecast_cf: pd.Series) -> np.ndarray:
        """Dress the published point forecast into quantiles."""
        point = forecast_cf.reindex(test.period_start).to_numpy()
        point = np.nan_to_num(point, nan=float(np.nanmean(test.cf)))
        return _dress(point, self._residuals, self.levels)
