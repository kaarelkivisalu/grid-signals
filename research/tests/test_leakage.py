"""The leakage guard.

Every feature column declares the latest instant its value may depend on, and this
asserts that instant never postdates the issue time. It is the load-bearing test of the
project: it caught a real defect on first run, where a fixed 24-hour NWP offset consumed
data that did not exist at issue time on 13 of every 24 delivery hours.
"""

from datetime import timedelta

import pandas as pd
import pytest

from renewable_forecast import windows
from renewable_forecast.features import assemble


def _frame(*, fixed_offset: int | None = None) -> pd.DataFrame:
    """A design-matrix skeleton spanning one full delivery day.

    With `fixed_offset` the naive construction is reproduced -- one offset for every
    hour -- which is what the guard must reject.
    """
    delivery = pd.Timestamp("2026-01-03")
    starts = pd.DatetimeIndex(windows.delivery_day_starts(delivery.date()))
    frame = pd.DataFrame(
        {
            "valid_time": starts,
            "delivery_day": delivery,
            "issue_day": delivery - pd.Timedelta(days=1),
            "power_curve_model_mean": 0.4,
            "wind_speed_100m_model_mean": 8.0,
            "lead_spread": 0.5,
            "hour_sin": 0.0,
            "lead_hour": 30,
            "cf_lag_48": 0.3,
            "cf_lag_72": 0.3,
            "cf_lag_168": 0.3,
            "cf": 0.4,
        }
    )
    frame["nwp_offset_days"] = (
        fixed_offset
        if fixed_offset is not None
        else assemble.required_offset(frame.valid_time, assemble.issue_time_of(frame))
    )
    return frame


def _violations(frame: pd.DataFrame) -> dict[str, int]:
    issued = assemble.issue_time_of(frame)
    sources = assemble.max_source_time(frame)
    return {
        column: int((sources[column] > issued).sum())
        for column in sources.columns
        if (sources[column] > issued).any()
    }


def test_every_feature_declares_its_information_age() -> None:
    frame = _frame()
    declared = assemble.provenance(frame)
    features = set(frame.columns) - {"cf", "mw", "capacity_mw"}
    assert set(declared) == features, "a feature without a declaration is unauditable"


def test_no_feature_may_postdate_the_issue_time() -> None:
    """The load-bearing assertion. Selecting the offset per hour must eliminate leaks."""
    assert not _violations(_frame()), "design matrix carries future information"


def test_a_fixed_24h_offset_would_leak() -> None:
    """Proof the guard fires: this is the defect it caught, preserved as a test."""
    leaked = _violations(_frame(fixed_offset=1))
    assert "power_curve_model_mean" in leaked
    assert leaked["power_curve_model_mean"] == 13, (
        "previous_day1 is legitimate for only the first 11 of 24 delivery hours"
    )


def test_a_48h_offset_is_always_safe_but_needlessly_stale() -> None:
    assert not _violations(_frame(fixed_offset=2))
    chosen = _frame().nwp_offset_days
    assert (chosen == 1).sum() == 11, (
        "the fresher offset should be used where it is safe"
    )


def test_required_offset_is_the_smallest_safe_one() -> None:
    frame = _frame()
    issued = assemble.issue_time_of(frame)
    age_hours = (frame.valid_time - issued).dt.total_seconds() / 3600
    chosen = assemble.required_offset(frame.valid_time, issued)
    assert (chosen * 24 >= age_hours).all(), (
        "chosen offset must not be fresher than the task"
    )
    assert ((chosen - 1) * 24 < age_hours).all(), (
        "a staler offset than necessary wastes skill"
    )


def test_lagged_actuals_are_stale_enough_for_the_latest_delivery_hour() -> None:
    """A 24 h lag is the intuitive choice and is wrong -- it leaks on later hours."""
    frame = _frame()
    latest_age = (
        frame.valid_time - assemble.issue_time_of(frame)
    ).dt.total_seconds().max() / 3600
    assert assemble.ACTUALS_MIN_AGE.total_seconds() / 3600 >= latest_age
    for lag in assemble.ACTUAL_LAGS_H:
        assert timedelta(hours=lag) >= assemble.ACTUALS_MIN_AGE


def test_calendar_features_are_known_arbitrarily_far_ahead() -> None:
    declared = assemble.provenance(_frame())
    for column in ("hour_sin", "lead_hour"):
        assert declared[column] is None


@pytest.mark.parametrize("lag", [48, 72, 168])
def test_lag_provenance_matches_the_column_name(lag: int) -> None:
    assert assemble.provenance(_frame())[f"cf_lag_{lag}"] == timedelta(hours=lag)


def test_the_operational_matrix_obeys_the_same_guard() -> None:
    """`build_operational` must not be a way around the leakage check.

    The forecasting path assembles its own rows for a day with no target, so it does not
    go through `build`. It shares `_annotate` and `required_offset` with the training
    path precisely so the guard still bites here; this asserts that it does.
    """
    delivery = pd.Timestamp("2026-01-03")
    frame = pd.DataFrame({"valid_time": windows.delivery_day_starts(delivery.date())})
    frame["valid_time"] = pd.to_datetime(frame.valid_time, utc=True)
    frame = assemble._annotate(frame)  # noqa: SLF001
    for lag in assemble.ACTUAL_LAGS_H:
        frame[f"cf_lag_{lag}"] = 0.3
    frame["power_curve_model_mean"] = 0.4

    issued = assemble.issue_time_of(frame)
    sources = assemble.max_source_time(frame)
    for column in sources.columns:
        late = int((sources[column] > issued).sum())
        assert late == 0, f"{column} postdates the issue time on {late} rows"


def test_operational_offsets_match_the_training_path() -> None:
    """The same delivery day must get the same vintage in both paths.

    A mismatch here would be train/serve skew of exactly the kind the whole vintage
    design exists to prevent, and it would be invisible in the backtest.
    """
    delivery = pd.Timestamp("2026-01-03")
    grid = pd.DataFrame({"valid_time": windows.delivery_day_starts(delivery.date())})
    grid["valid_time"] = pd.to_datetime(grid.valid_time, utc=True)
    operational = assemble._annotate(grid.copy())  # noqa: SLF001
    training = _frame()

    merged = operational.merge(
        training[["valid_time", "nwp_offset_days"]],
        on="valid_time",
        suffixes=("_operational", "_training"),
    )
    assert len(merged) == len(training)
    assert (merged.nwp_offset_days_operational == merged.nwp_offset_days_training).all()


def _meps_frame() -> pd.DataFrame:
    """A design-matrix skeleton carrying MEPS columns alongside the Open-Meteo ones."""
    frame = _frame()
    frame[assemble.MEPS_RUN_COLUMN] = frame.issue_day.dt.tz_localize("UTC")
    frame["power_curve__meps"] = 0.4
    frame["wind_speed_hub__meps"] = 8.0
    frame["power_curve__meps_ramp1"] = 0.01
    return frame


def test_meps_columns_are_declared_and_do_not_leak() -> None:
    frame = _meps_frame()
    declared = assemble.provenance(frame)
    assert "power_curve__meps" in declared
    assert not _violations(frame), "MEPS columns carry future information"


def test_meps_columns_are_dated_to_the_run_not_a_whole_day_offset() -> None:
    """The defining difference from the Open-Meteo path."""
    frame = _meps_frame()
    sources = assemble.max_source_time(frame)
    assert (sources["power_curve__meps"] == frame[assemble.MEPS_RUN_COLUMN]).all()
    assert (
        sources["power_curve__meps_ramp1"] == frame[assemble.MEPS_RUN_COLUMN]
    ).all(), "features derived from MEPS must inherit the run's information age"


def test_one_run_serves_the_whole_delivery_day() -> None:
    """This is the fix for the lead-34 step, stated as a property.

    Open-Meteo must switch offset partway through the delivery day, which is what puts
    a discontinuity in the error curve. A single MEPS run covers every hour, so its
    information age rises smoothly with lead time and never jumps.
    """
    frame = _meps_frame()
    assert frame.nwp_offset_days.nunique() == 2, (
        "the Open-Meteo path is expected to change vintage mid-day"
    )
    runs = frame[assemble.MEPS_RUN_COLUMN]
    assert (runs == runs.iloc[0]).all(), (
        "every delivery hour must be served by the same MEPS run"
    )

    age_h = (
        frame.valid_time - frame[assemble.MEPS_RUN_COLUMN]
    ).dt.total_seconds() / 3600
    steps = age_h.sort_values().diff().dropna()
    assert (steps == 1.0).all(), "information age must rise one hour per delivery hour"


def test_meps_run_precedes_the_issue_time_for_every_hour() -> None:
    frame = _meps_frame()
    assert (frame[assemble.MEPS_RUN_COLUMN] < assemble.issue_time_of(frame)).all()
