"""Portfolio navigation, honest availability, matched scores and time semantics."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from grid_signals.app.explorer_charts import coverage_map, forecast_chart
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
)
from grid_signals.app.markets import BY_CODE, COUNTRY_MARKETS
from grid_signals.app.model_catalogue import CATALOGUE, MODEL_DATA
from grid_signals.app.presentation import available_markets

APP = Path(__file__).parents[1] / "src/grid_signals/app/main.py"


def test_overview_is_populated_and_sidebar_is_just_navigation(monkeypatch):
    connect = Mock(side_effect=AssertionError("website opened a database"))
    monkeypatch.setattr("psycopg.connect", connect)
    monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert not app.sidebar.selectbox
    assert not app.sidebar.date_input
    assert [item.value for item in app.sidebar.title] == ["Grid Signals"]
    assert [item.value for item in app.sidebar.caption] == ["Nordic/Baltic electricity"]
    assert any("2026-09-19" in item.value for item in app.caption)
    assert not app.table[0].value.empty
    for page in (
        "wind",
        "solar",
        "price",
        "load",
        "performance",
        "methods",
        "coverage",
    ):
        app.switch_page(f"pages/{page}.py").run()
        assert not app.exception, page
        assert not app.error, page
    connect.assert_not_called()


@pytest.mark.parametrize(
    ("page", "target", "zone"),
    [
        ("wind", "wind_onshore", "SE3"),
        ("solar", "solar", "DE_LU"),
        ("price", "price", "DE_LU"),
        ("load", "load", "DE_LU"),
    ],
)
def test_product_pages_only_offer_real_forecasts(page, target, zone):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.switch_page(f"pages/{page}.py").run()
    assert not app.exception
    assert app.session_state["selected_zone"] == zone
    assert app.session_state["selected_target"] == target
    assert not app.selectbox
    assert not app.expander
    app.toggle(key=f"details_{target}").set_value(True).run()
    assert not app.button(key=f"market_{target}_{zone}").disabled
    other = "SE3" if zone == "DE_LU" else "DE_LU"
    assert app.button(key=f"market_{target}_{other}").disabled
    assert app.button(key=f"market_{target}_NO1").disabled
    day_control = next(item for item in app.selectbox if item.label == "Delivery date")
    day = day_control.value
    model = app.selectbox(key="selected_model").value
    forecasts = read_market(load_manifest(), zone, "forecast")
    pool = forecasts[
        (forecasts.target == target)
        & (forecasts.model == model)
        & (forecasts.split == "Final holdout")
    ]
    assert set(day_control.options) == set(pool.delivery_date.unique())
    assert day in day_control.options
    assert any(
        button.label == "Download forecast · CSV"
        for button in app.get("download_button")
    )


def test_nondefault_model_and_day_survive_informational_pages():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.switch_page("pages/wind.py").run()
    app.toggle(key="details_wind_onshore").set_value(True).run()
    app.selectbox(key="selected_model").set_value("physical_power_curve").run()
    control = next(item for item in app.selectbox if item.label == "Delivery date")
    chosen = control.options[2]
    control.set_value(chosen).run()
    for page in ("performance", "methods", "coverage", "overview", "wind"):
        app.switch_page(f"pages/{page}.py").run()
        assert not app.exception
        assert app.session_state["selected_zone"] == "SE3"
        assert app.session_state["selected_model"] == "physical_power_curve"
        assert app.session_state["delivery_date"] == date.fromisoformat(chosen)


@pytest.mark.parametrize("content", [None, {"schema_version": 99, "zones": {}}])
def test_unavailable_results_have_a_readable_state(tmp_path, monkeypatch, content):
    if content:
        (tmp_path / "manifest.json").write_text(json.dumps(content))
    monkeypatch.setenv("GRID_SIGNALS_EXPLORER_PATH", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert app.error[0].value == "Forecast results unavailable"


def test_publication_archive_displays_recorded_status_and_timestamp():
    manifest = load_manifest()
    pool = read_market(manifest, "SE3", "forecast")
    pool = pool[
        (pool.target == "wind_onshore")
        & (pool.model == "hourly_repeated")
        & (pool.split == "Published archive")
    ]
    expected = choose_curve(
        pool, "wind_onshore", pool.delivery_date.max(), "hourly_repeated"
    ).iloc[0]
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.switch_page("pages/wind.py").run()
    app.toggle(key="details_wind_onshore").set_value(True).run()
    app.selectbox(key="archive_wind_onshore").set_value("Published archive").run()
    assert not app.exception
    assert any(
        expected.publication_status in item.value
        and str(expected.published_at) in item.value
        for item in app.caption
    )
    app.toggle(key="details_wind_onshore").set_value(False).run()
    app.run()
    assert any(expected.publication_status in item.value for item in app.caption)
    app.toggle(key="details_wind_onshore").set_value(True).run()
    app.selectbox(key="archive_wind_onshore").set_value("Final holdout").run()
    assert not app.exception
    assert any("Final evaluation" in item.value for item in app.caption)


def test_performance_keeps_matched_metrics_and_detailed_period_controls():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.switch_page("pages/performance.py").run()
    assert not app.exception
    assert app.table[0].value["Average error (% capacity)"].min() == pytest.approx(
        2.46, abs=0.01
    )
    assert not app.metric
    app.toggle(key="details_performance").set_value(True).run()
    for group in ("Year", "Season", "Month", "Weekday", "Market quarter"):
        app.selectbox(key="score_group").set_value(group).run()
        assert not app.exception
        assert not app.dataframe[-1].value.empty
    app.button_group(key="selected_target").set_value("price").run()
    assert not app.exception
    assert app.session_state["selected_zone"] == "DE_LU"
    app.date_input(key="score_range_DE_LU_price_Final holdout").set_value(
        (date(2026, 9, 13), date(2026, 9, 13))
    ).run()
    assert any("No scored predictions" in item.value for item in app.info)
    app.date_input(key="score_range_DE_LU_price_Final holdout").set_value(
        (date(2026, 9, 14), date(2026, 9, 14))
    ).run()
    assert not app.exception
    assert app.dataframe[-1].value.Days.eq(1).all()
    assert app.dataframe[-1].value.model.nunique() == 4
    before = app.table[0].value.copy()
    app.toggle(key="details_performance").set_value(False).run()
    app.run()
    assert not app.exception
    pd.testing.assert_frame_equal(before, app.table[0].value)


def test_map_uses_country_fills_and_only_relevant_geography():
    figure = coverage_map(load_manifest())
    countries = {trace.meta["country"] for trace in figure.data if trace.meta}
    assert countries == set(COUNTRY_MARKETS)
    assert not countries & {"Russia", "Iceland", "France", "Turkey"}
    for trace in figure.data:
        assert "markers" not in trace.mode
        if trace.meta:
            assert trace.fill == "toself"
            if trace.meta["country"] == "Sweden":
                assert trace.meta["status"] == "Evaluated forecasts"
            if trace.meta["country"] == "Norway":
                assert trace.meta["status"] == "Planned"
    assert len({trace.fillcolor for trace in figure.data if trace.meta}) == 3


def test_observations_do_not_enable_unevaluated_forecasts():
    manifest = load_manifest()
    assert available_markets(manifest, "wind_onshore") == ["SE3"]
    assert available_markets(manifest, "solar") == ["DE_LU"]
    assert available_markets(manifest, "price") == ["DE_LU"]
    assert "FI" in manifest["zones"]


def test_every_model_has_explicit_sources_forecast_inputs_and_fitting_data():
    assert set(MODEL_DATA) == set(CATALOGUE)
    assert all(len(row) == 3 and all(row) for row in MODEL_DATA.values())
    assert "No weather" in MODEL_DATA["lear_hourly"][1]
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.switch_page("pages/methods.py").run()
    app.toggle(key="details_methods").set_value(True).run()
    for model in ("hourly_repeated", "interpolated_weather", "physical_power_curve"):
        app.selectbox(key="method_model").set_value(model).run()
        assert not app.exception
        assert any(MODEL_DATA[model][1] in item.value for item in app.markdown)
    app.button_group(key="selected_target").set_value("price").run()
    app.selectbox(key="method_model").set_value("lear_hourly").run()
    assert not app.exception
    assert any("No weather, demand or renewable" in item.value for item in app.markdown)


def test_default_chart_simplifies_uncertainty_without_losing_detailed_bands():
    pool = read_market(load_manifest(), "SE3", "forecast")
    rows = choose_curve(pool, "wind_onshore", "2026-09-19", "hourly_repeated")
    default = forecast_chart(rows, "Europe/Stockholm", "wind_onshore")
    full = forecast_chart(rows, "Europe/Stockholm", "wind_onshore", full_intervals=True)
    assert "80% range" in [trace.name for trace in default.data]
    assert "90% range" not in [trace.name for trace in default.data]
    assert {"50% range", "80% range", "90% range"} <= {
        trace.name for trace in full.data
    }


@pytest.mark.parametrize(
    "page", ["overview", "wind", "solar", "price", "performance", "methods", "coverage"]
)
def test_default_views_have_no_dropdowns_or_accordion_sections(page):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.switch_page(f"pages/{page}.py").run()
    assert not app.exception
    assert not app.selectbox
    assert not app.multiselect
    assert not app.date_input
    assert not app.radio
    assert not app.expander
    assert len(app.toggle) == 1
    assert app.toggle[0].label == "Details"


def test_forecast_error_panel_uses_the_same_times_and_actuals():
    pool = read_market(load_manifest(), "SE3", "forecast")
    rows = choose_curve(pool, "wind_onshore", "2026-09-19", "hourly_repeated")
    figure = forecast_chart(rows, "Europe/Stockholm", "wind_onshore", show_error=True)
    error = next(trace for trace in figure.data if trace.name == "Forecast - actual")
    np.testing.assert_allclose(error.y, rows["q0.50"] - rows.actual)
    assert list(error.x) == list(rows.valid_time)
    assert error.xaxis == "x2"
    assert figure.layout.xaxis.matches == "x2"


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
