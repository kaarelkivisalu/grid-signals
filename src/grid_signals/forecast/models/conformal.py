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


#: The NWP disagreement signal used to stratify. Among hours whose raw p10-p90 width is
#: the same, the quartile where the three models disagree most has roughly twice the
#: absolute error of the quartile where they agree, and 80% coverage falls from 0.81 to
#: 0.67 across those quartiles (`reports/calibration.md`). The booster sees this column
#: but does not widen its quantiles enough for it; a post-hoc layer can.
SPREAD_COLUMN = "power_curve_model_std"

#: Scores are divided by the raw interval width, floored so that near-zero widths at a
#: calm-night zero output cannot blow a residual up into an enormous normalised score.
MIN_SCALE = 0.02

SEASON_CODE = {"DJF": 0, "MAM": 1, "JJA": 2, "SON": 3}


class SpreadCQR:
    """Conformal quantile regression stratified by predicted level and NWP spread.

    Two changes from `StratifiedCQR`, each answering a measured defect:

    * **Strata that carry signal and stay populated.** Lead hour x level bin gives 96
      strata, and a 45-day calibration block puts ~11 rows in each, so most fall back
      to the global correction. Level bin x spread tercile gives 12, which stay above
      the fallback threshold in every fold, and spread is the stratifier the
      diagnostics say matters.
    * **Optionally multiplicative.** With `normalise=True` scores are `(y - q) / width`,
      so the correction stretches each forecast's own interval (the normalised-score
      variant of CQR). Measured on SE3 it scored slightly *worse* CRPS than additive
      scores within the same strata, so the shipping model uses `normalise=False`: the
      spread strata already carry the heteroscedasticity.

    Spread bin edges come from the calibration block's own terciles, so they adapt to
    each fold without looking at test data.
    """

    name = "conformal_spread"

    def __init__(
        self,
        levels: np.ndarray,
        spread_column: str = SPREAD_COLUMN,
        n_level_bins: int = N_PREDICTION_BINS,
        n_spread_bins: int = 3,
        *,
        normalise: bool = True,
        min_rows: int = 30,
        by_season: bool = False,
    ) -> None:
        self.levels = levels
        self.spread_column = spread_column
        self.n_level_bins = n_level_bins
        self.n_spread_bins = n_spread_bins
        self.normalise = normalise
        self.min_rows = min_rows
        # Season is only a usable stratum when the calibration set spans the year,
        # i.e. with cross-fitted residuals; a recent-quarter block holds one season.
        self.by_season = by_season
        self._level_edges = np.linspace(0.0, 1.0, n_level_bins + 1)[1:-1]
        self._spread_edges = np.array([])
        self._corrections: dict[tuple[int, int], np.ndarray] = {}
        self._by_level: dict[int, np.ndarray] = {}
        self._global = np.zeros(len(levels))

    def _median(self, quantiles: np.ndarray) -> np.ndarray:
        return quantiles[:, int(np.argmin(np.abs(self.levels - 0.5)))]

    def _scale(self, quantiles: np.ndarray) -> np.ndarray:
        if not self.normalise:
            return np.ones(len(quantiles))
        return np.maximum(quantiles[:, -1] - quantiles[:, 0], MIN_SCALE)

    def _spread(self, frame: pd.DataFrame) -> np.ndarray:
        if self.spread_column not in frame.columns:
            return np.zeros(len(frame))
        return frame[self.spread_column].to_numpy(dtype=float)

    def _bins(
        self, frame: pd.DataFrame, quantiles: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        level = np.digitize(self._median(quantiles), self._level_edges)
        if self.by_season and "season" in frame.columns:
            season = frame.season.map(SEASON_CODE).fillna(0).to_numpy(dtype=int)
            level = level + self.n_level_bins * season
        spread = self._spread(frame)
        # A missing spread (one model absent) goes to the middle bin rather than the
        # calmest one, which would tighten the interval exactly when information is thin.
        spread = np.where(np.isnan(spread), np.nanmedian(spread), spread)
        return level, np.digitize(spread, self._spread_edges)

    def _correction(self, scores: np.ndarray) -> np.ndarray:
        return np.quantile(scores, self.levels, axis=0).diagonal().copy()

    def fit(self, calibration: pd.DataFrame, quantiles: np.ndarray) -> "SpreadCQR":
        """Learn per-stratum corrections from held-out residuals."""
        actual = calibration.cf.to_numpy(dtype=float)
        spread = self._spread(calibration)
        finite = spread[np.isfinite(spread)]
        self._spread_edges = (
            np.quantile(finite, np.linspace(0, 1, self.n_spread_bins + 1)[1:-1])
            if len(finite)
            else np.array([])
        )
        scores = (actual[:, None] - quantiles) / self._scale(quantiles)[:, None]
        level, spread_bin = self._bins(calibration, quantiles)

        self._global = self._correction(scores)
        self._by_level, self._corrections = {}, {}
        for lb in np.unique(level):
            rows = level == lb
            if rows.sum() >= self.min_rows:
                self._by_level[int(lb)] = self._correction(scores[rows])
            for sb in np.unique(spread_bin[rows]):
                cell = rows & (spread_bin == sb)
                if cell.sum() >= self.min_rows:
                    self._corrections[(int(lb), int(sb))] = self._correction(
                        scores[cell]
                    )
        return self

    def apply(self, frame: pd.DataFrame, quantiles: np.ndarray) -> np.ndarray:
        """Stretch each interval by its stratum's correction, then repair crossings.

        Falls back from the (level, spread) cell to the level bin to the global
        correction, so a sparse stratum borrows from its nearest populated parent
        rather than from the whole calibration set at once.
        """
        level, spread_bin = self._bins(frame, quantiles)
        offsets = np.empty_like(quantiles)
        for position, (lb, sb) in enumerate(zip(level, spread_bin, strict=True)):
            key = (int(lb), int(sb))
            offsets[position] = self._corrections.get(
                key, self._by_level.get(key[0], self._global)
            )
        adjusted = quantiles + offsets * self._scale(quantiles)[:, None]
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
