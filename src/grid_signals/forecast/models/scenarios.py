"""Turn per-hour marginals into temporally coherent delivery-day scenarios.

The quantile model gives a distribution for each hour independently. That is enough to
score CRPS, and not enough for anything downstream: battery dispatch, imbalance cost and
net load all depend on how the 24 hours move *together*. A day that is windy all morning
and calm all afternoon and a day that alternates hour by hour can have identical
marginals and completely different value.

Two constructions, because marginal CRPS cannot tell them apart -- only the variogram and
energy scores can.
"""

import numpy as np
import pandas as pd
from scipy import stats


def gaussian_copula(
    quantiles: np.ndarray,
    levels: np.ndarray,
    correlation: np.ndarray,
    n_scenarios: int = 100,
    seed: int = 0,
) -> np.ndarray:
    """Sample joint paths by coupling the marginals through a Gaussian copula.

    Cheap and analytic, but it smooths away the sharp ramps that a real wind day
    contains -- Gaussian dependence has no tail dependence to speak of.
    """
    rng = np.random.default_rng(seed)
    n_hours = quantiles.shape[0]
    normal = rng.multivariate_normal(
        np.zeros(n_hours), correlation, size=n_scenarios, method="cholesky"
    )
    uniform = stats.norm.cdf(normal)
    return np.column_stack(
        [
            np.interp(uniform[:, hour], levels, quantiles[hour])
            for hour in range(n_hours)
        ]
    )


def schaake_shuffle(
    quantiles: np.ndarray,
    levels: np.ndarray,
    analogues: np.ndarray,
    seed: int = 0,
) -> np.ndarray:
    """Impose the rank structure of historical days onto the forecast marginals.

    Non-parametric and the default recommendation: it borrows the dependence structure
    from days that actually happened, so ramp shapes stay realistic instead of being
    averaged into smoothness.

    `analogues` is (n_scenarios, n_hours) of historical capacity factors.
    """
    rng = np.random.default_rng(seed)
    n_scenarios, n_hours = analogues.shape
    draws = np.column_stack(
        [
            np.interp(rng.uniform(size=n_scenarios), levels, quantiles[hour])
            for hour in range(n_hours)
        ]
    )
    out = np.empty_like(draws)
    for hour in range(n_hours):
        # Place the sorted forecast draws in the rank order the historical day had.
        order = np.argsort(np.argsort(analogues[:, hour]))
        out[:, hour] = np.sort(draws[:, hour])[order]
    return out


def pick_analogues(
    history: pd.DataFrame, target_profile: np.ndarray, n: int = 100
) -> np.ndarray:
    """Choose the historical days whose shape most resembles the forecast profile.

    Similarity is on the normalised profile, not the level: what is being borrowed is
    the dependence structure, not the magnitude.
    """

    def normalise(array: np.ndarray) -> np.ndarray:
        centred = array - array.mean(axis=-1, keepdims=True)
        return centred / (array.std(axis=-1, keepdims=True) + 1e-9)

    matrix = history.to_numpy()
    distance = np.linalg.norm(
        normalise(matrix) - normalise(target_profile)[None, :], axis=1
    )
    return matrix[np.argsort(distance)[:n]]


def empirical_correlation(history: pd.DataFrame) -> np.ndarray:
    """Hour-to-hour correlation of the target, in normal scores.

    Rank-transforming first keeps the copula estimate from being dominated by the
    skewed shape of the capacity-factor distribution.
    """
    ranks = history.rank(axis=0, pct=True).clip(0.001, 0.999)
    scores = stats.norm.ppf(ranks.to_numpy())
    correlation = np.corrcoef(scores, rowvar=False)
    # Nudge onto the positive-definite cone so Cholesky sampling cannot fail.
    eigenvalues, vectors = np.linalg.eigh(correlation)
    eigenvalues = np.clip(eigenvalues, 1e-6, None)
    fixed = vectors @ np.diag(eigenvalues) @ vectors.T
    scale = np.sqrt(np.diag(fixed))
    return fixed / np.outer(scale, scale)
