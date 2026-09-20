"""Conformal calibration of quantile forecasts.

Two departures from textbook split-conformal, both forced by the data:

* **Stratified, not global.** A single correction would over-widen the intervals where
  the forecast is already sharp and under-widen them where it is not. Corrections are
  fitted per lead hour and per predicted-level bin.
* **Adaptive, not one-shot.** Split-conformal's coverage guarantee assumes
  exchangeability, which a time series violates: weather regimes persist, and the fleet
  changes underneath. Adaptive conformal inference nudges the working level after each
  batch so realised coverage tracks the nominal one instead of drifting away from it.
"""

import numpy as np
import pandas as pd

#: How fast the working level chases realised coverage. Small enough to be stable,
#: large enough to track a regime change within a season.
DEFAULT_STEP = 0.01

#: Predicted-level bins. Uncertainty near zero output behaves very differently from
#: uncertainty near rated, so one correction for both would fit neither.
N_PREDICTION_BINS = 4


class StratifiedCQR:
    """Conformalised quantile regression, stratified by lead hour and output level."""

    name = "conformal"

    def __init__(
        self,
        levels: np.ndarray,
        step: float = DEFAULT_STEP,
        n_bins: int = N_PREDICTION_BINS,
    ) -> None:
        self.levels = levels
        self.step = step
        self.n_bins = n_bins
        self._corrections: dict[tuple, np.ndarray] = {}
        self._global = np.zeros(len(levels))
        self._edges = np.linspace(0.0, 1.0, n_bins + 1)

    def _strata(self, frame: pd.DataFrame, point: np.ndarray) -> pd.Series:
        lead = (
            frame.lead_hour.to_numpy()
            if "lead_hour" in frame.columns
            else np.zeros(len(frame))
        )
        bins = np.clip(np.digitize(point, self._edges[1:-1]), 0, self.n_bins - 1)
        return pd.Series(list(zip(lead, bins, strict=True)), index=frame.index)

    def fit(self, calibration: pd.DataFrame, quantiles: np.ndarray) -> "StratifiedCQR":
        """Learn per-stratum additive corrections from held-out residuals.

        The correction for a level is the quantile of the conformity scores at that
        level, which is what makes the adjusted interval attain nominal coverage on
        data drawn like the calibration set.
        """
        actual = calibration.cf.to_numpy()
        median = quantiles[:, int(np.argmin(np.abs(self.levels - 0.5)))]
        strata = self._strata(calibration, median)

        scores = actual[:, None] - quantiles
        self._global = np.quantile(scores, self.levels, axis=0).diagonal().copy()

        self._corrections = {}
        for key, index in calibration.groupby(strata).groups.items():
            rows = calibration.index.get_indexer(index)
            if len(rows) < 30:
                continue
            self._corrections[key] = (
                np.quantile(scores[rows], self.levels, axis=0).diagonal().copy()
            )
        return self

    def apply(self, frame: pd.DataFrame, quantiles: np.ndarray) -> np.ndarray:
        """Apply the fitted corrections and repair any crossings."""
        median = quantiles[:, int(np.argmin(np.abs(self.levels - 0.5)))]
        strata = self._strata(frame, median)
        adjusted = quantiles.copy()
        for position, key in enumerate(strata):
            adjusted[position] += self._corrections.get(key, self._global)
        return np.sort(np.clip(adjusted, 0.0, 1.0), axis=1)


def adaptive_levels(
    realised_coverage: np.ndarray, nominal: np.ndarray, step: float = DEFAULT_STEP
) -> np.ndarray:
    """One adaptive-conformal update of the working levels.

    Where realised coverage has fallen short of nominal the working level is pushed out,
    and where it has overshot it is pulled in. Applied online, this keeps coverage
    tracking the target under the non-exchangeability that a time series guarantees.
    """
    return np.clip(nominal + step * (nominal - realised_coverage), 0.001, 0.999)
