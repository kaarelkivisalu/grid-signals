"""Historical selection, matched scores, time resolution and market coverage."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from grid_signals.app.explorer_data import (
    choose_curve,
    complete_hourly,
    group_labels,
    grouped_scores,
    load_manifest,
    market_day,
    market_quarters,
    matched_rows,
    read_market,
    suggested_backtest_day,
)
from grid_signals.app.markets import BY_CODE

APP = Path(__file__).parents[1] / "src/grid_signals/app/main.py"


@pytest.mark.parametrize("demo_only", [False, True])
def test_shared_selection_survives_navigation_without_operational_services(
    monkeypatch, demo_only
):
    monkeypatch.setenv("GRID_SIGNALS_DEMO_ONLY", "1" if demo_only else "0")
    connect = Mock(side_effect=AssertionError("demo opened a database"))
    monkeypatch.setattr("psycopg.connect", connect)
    monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    app.selectbox(key="selected_zone").set_value("DE_LU").run()
    app.date_input(key="delivery_date").set_value(date(2026, 9, 2)).run()
    app.selectbox(key="selected_target").set_value("solar").run()
    assert not app.exception
    for page in ["performance", "methods", "coverage", "overview"]:
        app.switch_page(f"pages/{page}.py").run()
        assert not app.exception
        assert app.session_state["selected_zone"] == "DE_LU"
        assert app.session_state["delivery_date"] == date(2026, 9, 2)
        assert app.session_state["selected_target"] == "solar"
        assert app.session_state["selected_model"] == "solar_quantile"
    app.selectbox(key="selected_zone").set_value("SE3").run()
    app.selectbox(key="selected_target").set_value("wind_onshore").run()
    assert app.session_state["selected_model"] == "hourly_repeated"
    app.switch_page("pages/performance.py").run()
    assert app.metric[0].value == "2.46"
    for group in ["Year", "Season", "Month", "Weekday", "Market quarter"]:
        app.selectbox(key="score_group").set_value(group).run()
        assert not app.exception
        assert not app.dataframe[0].value.empty
    connect.assert_not_called()


def test_missing_date_and_unmodelled_area_are_explicit():
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.date_input(key="delivery_date").set_value(date(2020, 1, 1)).run()
    assert not app.exception
    assert any("No onshore wind model output" in info.value for info in app.info)
    app.selectbox(key="selected_zone").set_value("FI").run()
    app.date_input(key="delivery_date").set_value(date(2026, 9, 19)).run()
    assert not app.exception
    assert app.session_state["selected_model"] is None
    app.switch_page("pages/performance.py").run()
    assert "No model has been backtested" in app.info[0].value
    app.selectbox(key="selected_zone").set_value("CH").run()
    app.switch_page("pages/overview.py").run()
    assert not app.exception
    assert "no data bundled" in app.info[0].value


@pytest.mark.parametrize("content", [None, {"schema_version": 99, "zones": {}}])
def test_unavailable_explorer_has_readable_empty_state(tmp_path, monkeypatch, content):
    if content:
        (tmp_path / "manifest.json").write_text(json.dumps(content))
    monkeypatch.setenv("GRID_SIGNALS_EXPLORER_PATH", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert app.error[0].value == "Market explorer unavailable"


@pytest.mark.parametrize(
    ("day", "intervals"), [("2026-03-29", 92), ("2026-10-25", 100)]
)
def test_market_quarter_is_elapsed_order_through_dst(day, intervals):
    frame = market_day(pd.DataFrame(), day, "Europe/Berlin")
    quarters = market_quarters(pd.Series(frame.index), "Europe/Berlin")
    assert len(frame) == intervals
    assert quarters.tolist() == list(range(1, intervals + 1))
    assert frame.index.is_unique


def test_calendar_groups_use_market_local_date_and_winter_year():
    frame = pd.DataFrame(
        {"valid_time": pd.to_datetime(["2025-12-31T23:00Z", "2026-05-31T22:00Z"])}
    )
    assert group_labels(frame, "Year", "Europe/Berlin").tolist() == ["2026", "2026"]
    assert group_labels(frame, "Season", "Europe/Berlin").tolist() == [
        "2026 · 1 Winter",
        "2026 · 3 Summer",
    ]
    assert group_labels(frame, "Weekday", "Europe/Berlin").tolist() == [
        "4 Thu",
        "1 Mon",
    ]


def test_matched_metrics_weight_intervals_and_do_not_fill_a_missing_model():
    times = pd.date_range("2026-09-01T00:00Z", periods=5, freq="15min")
    base = pd.DataFrame(
        {
            "valid_time": times,
            "delivery_date": ["2026-09-01"] * 4 + ["2026-09-02"],
            "split": "Final holdout",
            "actual": 10.0,
            "eligible": True,
            "mae": [0, 0, 0, 0, 10],
            "crps": 1.0,
            "bias": -1.0,
            "coverage_80": True,
            "coverage_90": True,
        }
    )
    rows = pd.concat(
        [base.assign(model="one"), base.assign(model="two")], ignore_index=True
    )
    score = grouped_scores(
        matched_rows(rows, ["one", "two"]), "Overall", "Europe/Berlin"
    )
    assert score.MAE.tolist() == [2.0, 2.0]  # Not the mean of daily means (5).
    assert score.Intervals.tolist() == [5, 5]
    missing = rows.drop(index=9)
    matched = matched_rows(missing, ["one", "two"])
    assert len(matched) == 8
    assert grouped_scores(matched, "Overall", "Europe/Berlin").MAE.tolist() == [0, 0]
    changed = rows.copy()
    changed.loc[9, "actual"] = 20
    with pytest.raises(ValueError, match="different scoring targets"):
        matched_rows(changed, ["one", "two"])


def test_hourly_display_does_not_average_incomplete_observations():
    index = pd.date_range("2026-10-15T00:00Z", periods=8, freq="15min")
    frame = pd.DataFrame({"load": [1, 2, 3, 4, 1, 2, np.nan, 4]}, index=index)
    hourly = complete_hourly(frame)
    assert hourly.load.iloc[0] == 2.5
    assert pd.isna(hourly.load.iloc[1])


def test_full_portable_archive_matches_released_headlines_and_real_market_coverage():
    manifest = load_manifest()
    assert set(manifest["zones"]) >= {
        "DE_LU",
        "SE1",
        "SE2",
        "SE3",
        "SE4",
        "FI",
        "EE",
        "FR",
        "NL",
        "DK1",
        "DK2",
    }
    assert not BY_CODE["CH"].sdac
    assert not BY_CODE["GB"].sdac
    assert BY_CODE["IE_SEM"].sdac
    frame = read_market(manifest, "DE_LU", "forecast")
    for target, model, expected in [
        ("price", "lear_hourly", 37.21),
        ("load", "load_quantile_gbm", 1433.4),
        ("solar", "solar_quantile", 2.8354),
    ]:
        rows = frame[(frame.target == target) & (frame.split == "Final holdout")]
        score = grouped_scores(
            matched_rows(rows, [model]),
            "Overall",
            "Europe/Berlin",
            capacity=target == "solar",
        )
        assert score.MAE.iloc[0] == pytest.approx(expected, abs=0.02)
    actual = read_market(manifest, "DE_LU", "observation").dropna(
        subset=["residual_load"]
    )
    pd.testing.assert_series_equal(
        actual.residual_load,
        actual.load - actual.solar - actual.wind_onshore - actual.wind_offshore,
        check_names=False,
    )


def test_selected_date_can_score_one_day_and_keeps_missing_days_explicit():
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.selectbox(key="selected_zone").set_value("DE_LU").run()
    app.selectbox(key="selected_target").set_value("price").run()
    app.date_input(key="delivery_date").set_value(date(2026, 9, 13)).run()
    app.switch_page("pages/performance.py").run()
    next(
        button for button in app.button if button.label == "Use explorer delivery date"
    ).click().run()
    assert not app.exception
    assert any(
        "No scored predictions in this date range" in info.value for info in app.info
    )
    app.date_input(key="delivery_date").set_value(date(2026, 9, 14)).run()
    next(
        button for button in app.button if button.label == "Use explorer delivery date"
    ).click().run()
    assert not app.exception
    assert app.metric[3].value == "1 / 96"


def test_latest_publication_has_actual_status_and_can_return_to_shared_backtest():
    manifest = load_manifest()
    latest_day = manifest["zones"]["SE3"]["dates"][-1]
    expected = choose_curve(
        read_market(manifest, "SE3", "forecast"),
        "wind_onshore",
        latest_day,
        "hourly_repeated",
    ).iloc[0]
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    next(
        button for button in app.button if button.label == "Latest forecast / data"
    ).click().run()
    assert not app.exception
    assert any(
        f"Publication status: {expected.publication_status}." in info.value
        and str(expected.published_at) in info.value
        for info in app.info
    )
    next(
        button for button in app.button if button.label == "Latest joint backtest"
    ).click().run()
    assert not app.exception
    assert app.session_state["delivery_date"] == date.fromisoformat(
        suggested_backtest_day(manifest["zones"]["SE3"])
    )


def test_demo_opens_on_scored_se3_wind_and_never_exposes_old_tools():
    app = AppTest.from_file(str(APP), default_timeout=20)
    app.session_state["show_market_tools"] = True
    app.run()
    assert not app.exception
    assert app.session_state["selected_zone"] == "SE3"
    assert app.session_state["selected_target"] == "wind_onshore"
    assert app.session_state["selected_model"] == "hourly_repeated"
    assert (
        next(
            item for item in app.selectbox if item.label == "Compare median with"
        ).value
        == "physical_power_curve"
    )
    assert any("Final holdout" in caption.value for caption in app.caption)
    assert any(
        button.label == "Download this forecast · CSV"
        for button in app.get("download_button")
    )
    assert "More tools" not in [item.label for item in app.expander]
    assert all(item.key != "show_market_tools" for item in app.toggle)
