"""Tests for the feature-block A/B: arms must differ by their blocks and nothing else."""

import pandas as pd
import pytest

from grid_signals.forecast.features import assemble
from grid_signals.forecast.pipelines import compare_blocks


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cf": [0.4],
            "power_curve_model_mean": [0.4],
            f"{assemble.PRICE_PREFIX}same_hour": [-3.0],
            f"{assemble.RESIDUAL_PREFIX}8h_anom": [0.01],
        }
    )


def test_base_arm_hides_both_blocks() -> None:
    columns = set(compare_blocks.arm_frame(_frame(), "base").columns)
    assert columns == {"cf", "power_curve_model_mean"}


@pytest.mark.parametrize(
    ("arm", "prefix"),
    [("prices", assemble.PRICE_PREFIX), ("residuals", assemble.RESIDUAL_PREFIX)],
)
def test_single_block_arms_add_exactly_their_block(arm: str, prefix: str) -> None:
    base = set(compare_blocks.arm_frame(_frame(), "base").columns)
    extra = set(compare_blocks.arm_frame(_frame(), arm).columns) - base
    assert extra
    assert all(c.startswith(prefix) for c in extra)


def test_both_arm_sees_every_column_once() -> None:
    columns = list(compare_blocks.arm_frame(_frame(), "both").columns)
    assert sorted(columns) == sorted(_frame().columns)


def test_unknown_arm_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown arm"):
        compare_blocks.arm_frame(_frame(), "nonsense")
