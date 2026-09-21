"""Shared feature handling for every model.

One place decides what counts as a feature, so a model cannot accidentally train on the
target, a metadata column, or anything the leakage guard has not vetted.
"""

import numpy as np
import pandas as pd

#: Never features: the target itself, quantities derived from it, and task bookkeeping.
EXCLUDED = frozenset(
    {
        "cf",
        "mw",
        "capacity_mw",
        "valid_time",
        "delivery_day",
        "issue_day",
        "season",
        "nwp_offset_days",
        # The MEPS run instant is bookkeeping, not weather: it tells the leakage guard
        # how old a __meps column is and must never become a feature itself.
        "meps_run_time",
    }
)

#: Features the fleet response is physically monotone in. Constraining them is cheap
#: insurance against nonsense in the sparse high-wind tail, where a short archive gives
#: a tree almost nothing to learn from.
MONOTONE_INCREASING = (
    "power_curve_model_mean",
    "wind_speed_100m_model_mean",
    "power_curve__meps",
    "wind_speed_hub__meps",
)


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """Numeric columns a model may use."""
    return [
        column
        for column in frame.columns
        if column not in EXCLUDED and pd.api.types.is_numeric_dtype(frame[column])
    ]


def monotone_constraints(columns: list[str]) -> list[int]:
    """LightGBM constraint vector aligned to `columns`."""
    return [1 if column in MONOTONE_INCREASING else 0 for column in columns]


def matrix(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    """Feature matrix as float, with non-finite values left for the learner to handle."""
    return frame[columns].to_numpy(dtype=float)
