"""Scoring. Point metrics are normalised by installed capacity, never by mean output.

Normalising by mean generation makes numbers incomparable across years as the fleet
grows -- the same physical error looks like an improvement simply because the
denominator got bigger.
"""

import numpy as np
import pandas as pd
import scoringrules as sr


def nmae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean absolute error in capacity-factor units."""
    return float(np.nanmean(np.abs(actual - predicted)))


def nrmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Root mean squared error in capacity-factor units."""
    return float(np.sqrt(np.nanmean((actual - predicted) ** 2)))


def nbias(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean signed error; positive means the forecast runs low."""
    return float(np.nanmean(actual - predicted))


def pinball(
    actual: np.ndarray, quantiles: np.ndarray, levels: np.ndarray
) -> np.ndarray:
    """Pinball loss per quantile level. `quantiles` is (n_obs, n_levels)."""
    diff = actual[:, None] - quantiles
    return np.nanmean(np.maximum(levels * diff, (levels - 1) * diff), axis=0)


def crps(actual: np.ndarray, quantiles: np.ndarray, levels: np.ndarray) -> float:
    """Continuous ranked probability score from a quantile forecast."""
    return float(np.nanmean(sr.crps_quantile(actual, quantiles, levels)))


def coverage(
    actual: np.ndarray, quantiles: np.ndarray, levels: np.ndarray, nominal: float = 0.80
) -> float:
    """Empirical coverage of the central interval at a nominal level."""
    lo_level, hi_level = (1 - nominal) / 2, 1 - (1 - nominal) / 2
    lo = quantiles[:, int(np.argmin(np.abs(levels - lo_level)))]
    hi = quantiles[:, int(np.argmin(np.abs(levels - hi_level)))]
    return float(np.nanmean((actual >= lo) & (actual <= hi)))


def sharpness(
    quantiles: np.ndarray, levels: np.ndarray, nominal: float = 0.80
) -> float:
    """Mean width of the central interval. Only meaningful alongside coverage."""
    lo_level, hi_level = (1 - nominal) / 2, 1 - (1 - nominal) / 2
    lo = quantiles[:, int(np.argmin(np.abs(levels - lo_level)))]
    hi = quantiles[:, int(np.argmin(np.abs(levels - hi_level)))]
    return float(np.nanmean(hi - lo))


def pit(actual: np.ndarray, quantiles: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """Probability integral transform: the predictive CDF evaluated at each observation.

    A calibrated forecast gives a uniform result. A U shape means underdispersion -- the
    usual failure of raw ensembles -- and a hump means overdispersion.

    The value is interpolated between quantile levels rather than snapped to the nearest
    one. Snapping collapses "below every quantile" and "inside the first interval" onto
    the same level, which doubles the mass in the lowest bin and makes a perfectly
    calibrated forecast look miscalibrated.
    """
    return np.array(
        [
            np.interp(a, q, levels, left=0.0, right=1.0)
            for a, q in zip(actual, quantiles, strict=True)
        ]
    )


def skill_score(score: float, reference: float) -> float:
    """Fractional improvement over a reference score; positive is better."""
    return float(1 - score / reference) if reference else float("nan")


def summarise(
    actual: np.ndarray,
    quantiles: np.ndarray,
    levels: np.ndarray,
    median_index: int | None = None,
) -> dict[str, float]:
    """The standard metric bundle for one set of predictions."""
    idx = (
        median_index
        if median_index is not None
        else int(np.argmin(np.abs(levels - 0.5)))
    )
    point = quantiles[:, idx]
    return {
        "nmae": nmae(actual, point),
        "nrmse": nrmse(actual, point),
        "nbias": nbias(actual, point),
        "crps": crps(actual, quantiles, levels),
        "pinball_mean": float(np.mean(pinball(actual, quantiles, levels))),
        "coverage_80": coverage(actual, quantiles, levels, 0.80),
        "coverage_90": coverage(actual, quantiles, levels, 0.90),
        "sharpness_80": sharpness(quantiles, levels, 0.80),
    }


def by_segment(
    frame: pd.DataFrame, actual: str, point: str, group: str
) -> pd.DataFrame:
    """Point metrics broken down by a segment column (lead hour, season, ...)."""
    return (
        frame.groupby(group)
        .apply(
            lambda g: pd.Series(
                {
                    "n": len(g),
                    "nmae": nmae(g[actual].to_numpy(), g[point].to_numpy()),
                    "nrmse": nrmse(g[actual].to_numpy(), g[point].to_numpy()),
                    "nbias": nbias(g[actual].to_numpy(), g[point].to_numpy()),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
