"""Tests for the MEPS A/B comparison.

The comparison only means anything if the arms differ by *information* and nothing
else, so what is worth testing is the bookkeeping: that the arms partition the columns
cleanly, that every arm sees the same rows, and that the step statistic measures what
it claims to.
"""

import numpy as np
import pandas as pd
import pytest

from grid_signals.forecast.pipelines import compare_meps


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cf": 0.4,
            "capacity_mw": 4656.0,
            "valid_time": pd.date_range("2025-01-02", periods=4, tz="UTC", freq="h"),
            "delivery_day": pd.Timestamp("2025-01-02"),
            "lead_hour": [30, 31, 32, 33],
            "cf_lag_48": 0.3,
            "hour_sin": 0.1,
            "power_curve_model_mean": 0.4,
            "wind_speed_100m_model_mean": 8.0,
            "meps_run_time": pd.Timestamp("2025-01-01", tz="UTC"),
            "power_curve__meps": 0.42,
            "power_curve__meps_ramp1": 0.01,
        }
    )


def test_arms_partition_the_columns_without_overlap() -> None:
    frame = _frame()
    both = compare_meps.arm_columns(frame, "both")
    assert len(both) == len(set(both)), "a column must not appear twice in one arm"
    assert set(both) == set(frame.columns), "the `both` arm must see everything"


def test_openmeteo_arm_hides_every_meps_column() -> None:
    columns = compare_meps.arm_columns(_frame(), "openmeteo")
    assert "power_curve__meps" not in columns
    assert "power_curve__meps_ramp1" not in columns, (
        "derived MEPS columns must be hidden too, or the arm leaks the source it tests"
    )
    assert "power_curve_model_mean" in columns


def test_meps_arm_hides_the_openmeteo_weather_block() -> None:
    columns = compare_meps.arm_columns(_frame(), "meps")
    assert "power_curve_model_mean" not in columns
    assert "power_curve__meps" in columns


def test_every_arm_keeps_the_target_and_the_shared_columns() -> None:
    for arm in compare_meps.ARMS:
        columns = compare_meps.arm_columns(_frame(), arm)
        for required in ("cf", "valid_time", "delivery_day", "cf_lag_48", "hour_sin"):
            assert required in columns, f"{arm} dropped {required}"


def test_unknown_arm_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown arm"):
        compare_meps.arm_columns(_frame(), "nonsense")


def test_covered_drops_whole_days_not_scattered_hours() -> None:
    """A partly covered day would make the arms differ by sample within a day."""
    frame = pd.concat(
        [
            _frame(),
            _frame().assign(
                delivery_day=pd.Timestamp("2025-01-03"), power_curve__meps=np.nan
            ),
        ],
        ignore_index=True,
    )
    kept = compare_meps.covered(frame)
    assert kept.delivery_day.unique().tolist() == [pd.Timestamp("2025-01-02")]


def test_step_statistic_detects_a_jump() -> None:
    flat = pd.DataFrame({"lead_hour": range(28, 40), "nmae": 0.02})
    assert compare_meps.step_at(flat) == pytest.approx(0.0)

    stepped = flat.copy()
    stepped.loc[stepped.lead_hour >= 34, "nmae"] = 0.027
    assert compare_meps.step_at(stepped) == pytest.approx(0.35, abs=1e-9)


def _ifs_frame() -> pd.DataFrame:
    frame = _frame()
    frame["ifs_run_time"] = pd.Timestamp("2025-01-01", tz="UTC")
    frame["power_curve__ifsrun"] = 0.41
    frame["power_curve_runs_std__meps__ifsrun"] = 0.01
    frame["power_curve_model_std"] = 0.02
    return frame


def test_meps_arm_never_sees_ifs_information() -> None:
    """The cross-source spread carries the MEPS marker but is built from IFS too."""
    columns = compare_meps.arm_columns(_ifs_frame(), "meps")
    assert "power_curve__ifsrun" not in columns
    assert "power_curve_runs_std__meps__ifsrun" not in columns


def test_runs_arm_has_no_whole_day_vintaged_column() -> None:
    columns = compare_meps.arm_columns(_ifs_frame(), "runs")
    assert "power_curve_model_mean" not in columns
    assert "power_curve_model_std" not in columns
    assert {"power_curve__meps", "power_curve__ifsrun"} <= set(columns)


def test_runs_om_spread_arm_adds_only_disagreement_columns() -> None:
    frame = _ifs_frame()
    extra = set(compare_meps.arm_columns(frame, "runs_om_spread")) - set(
        compare_meps.arm_columns(frame, "runs")
    )
    assert extra == {"power_curve_model_std"}


def test_all_arm_sees_every_column_once() -> None:
    frame = _ifs_frame()
    columns = compare_meps.arm_columns(frame, "all")
    assert len(columns) == len(set(columns))
    assert set(columns) == set(frame.columns)
