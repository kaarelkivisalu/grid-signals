"""Figures for the research reports.

Every chart is generated from the artifacts a backtest already wrote -- the MLflow
metric store and the per-run parquet grids -- so a figure cannot drift away from the
number it illustrates. Regenerate with::

    PYTHONPATH=research/src uv run python -m renewable_forecast.reporting.figures
"""

import logging
import sqlite3

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from renewable_forecast import paths, windows

logger = logging.getLogger(__name__)

FIGURES = paths.REPORTS / "figures"

#: Delivery days are defined in market local time, so that is what the charts show.
MARKET_TZ = windows.MARKET_TZ
TRACKING_DB = paths.MLRUNS / "mlflow.db"
ARTIFACTS = paths.MLRUNS / "artifacts"

#: Drawing order, worst to best, so legends and bar charts read top-down.
ORDER = (
    "persistence",
    "climatology",
    "ridge_sanity_floor",
    "physical_power_curve",
    "lightgbm_point_monotone",
    "lightgbm_quantile",
    "A69_latest_vintage",
)
COLOURS = {
    "persistence": "#b0b0b0",
    "climatology": "#8a8a8a",
    "ridge_sanity_floor": "#8cb369",
    "physical_power_curve": "#5b8e7d",
    "lightgbm_point_monotone": "#f4a259",
    "lightgbm_quantile": "#bc4b51",
    "A69_latest_vintage": "#4f6d7a",
}
#: A69 is served at its latest revision, so it is drawn dashed everywhere and never
#: presented as a bar the models are asked to clear. See reports/protocol.md.
REFERENCE = "A69_latest_vintage"

NOMINAL_80 = 0.80
NOMINAL_90 = 0.90

#: Lead hour at which Open-Meteo's day-granular vintage forces a 24 h older run.
VINTAGE_BOUNDARY = 34

#: Landmarks on the 00z-run clock, in hours. Gate closure is 12:00 local, which is
#: 11:00 UTC under CET and 10:00 UTC under CEST; the delivery day is 00:00-24:00 local,
#: so under CET it opens at 23:00 UTC on day D (+23) and closes 24 h later (+47).
ISSUE_HOUR_UTC = 9
GATE_CLOSURE_CET = 11
DELIVERY_START_CET = 23
DELIVERY_END_CET = 47

#: A 00z run is not usable at 00z -- it has to finish and be disseminated first, which
#: is the real constraint on how early the issue time can be. GFS 00z lands from about
#: 03:30 UTC; ECMWF HRES 00z disseminates in tranches from 05:45 to 07:34 UTC, and the
#: steps this task needs (<= +90 h) are in the earlier ones. ECMWF is the binding model.
#: These are the producers' own schedules; Open-Meteo's derived product adds further
#: latency that this project has not measured.
NWP_FIRST_AVAILABLE = 3.5
NWP_LAST_AVAILABLE = 7.6


def _save(fig: plt.Figure, name: str) -> str:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / f"{name}.png"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info("wrote %s", path)
    return path.name


def latest_runs() -> pd.DataFrame:
    """Return the most recent finished run per forecaster, with its headline metrics."""
    with sqlite3.connect(TRACKING_DB) as con:
        runs = pd.read_sql(
            "select run_uuid, name, start_time from runs where status = 'FINISHED'",
            con,
        )
        metrics = pd.read_sql("select run_uuid, key, value from latest_metrics", con)
    newest = runs.sort_values("start_time").groupby("name").tail(1)
    grid = (
        metrics.pivot(index="run_uuid", columns="key", values="value")
        .reset_index()
        .merge(newest, on="run_uuid")
    )
    grid["rank"] = grid.name.map({n: i for i, n in enumerate(ORDER)})
    return grid.sort_values("rank").reset_index(drop=True)


def run_artifact(run_uuid: str, name: str) -> pd.DataFrame:
    """Load one per-run metric grid written by the backtest."""
    return pd.read_parquet(ARTIFACTS / run_uuid / "artifacts" / f"{name}.parquet")


def evaluation_window() -> dict:
    """The exact rows every headline metric is computed over.

    Recomputed from the config and the split functions rather than transcribed, so the
    documented population cannot drift away from the scored one.
    """
    from renewable_forecast import config
    from renewable_forecast.evaluation import splits
    from renewable_forecast.pipelines import evaluate

    cfg = config.load()
    frame = evaluate.load_design_matrix()
    development, holdout = evaluate.development_split(frame, cfg)
    folds = splits.rolling_origin(
        development, cfg.splits.embargo_days, cfg.splits.origin_freq, min_train_days=180
    )
    tested = pd.DatetimeIndex(sorted(set().union(*[set(f.test_days) for f in folds])))
    return {
        "frame": frame,
        "development": development,
        "holdout": holdout,
        "folds": folds,
        "tested": tested,
        "rows": frame[frame.delivery_day.isin(tested)],
    }


def plot_evaluation_window() -> str:
    """Which delivery days each metric is actually computed over.

    The development window is not the scored window. The first folds need 180 training
    days before they can test anything, and the last monthly origin stops short of the
    development end, so 217 development days never appear in any test set.
    """
    window = evaluation_window()
    folds, tested = window["folds"], window["tested"]
    development, holdout = window["development"], window["holdout"]

    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(11, 4.4), height_ratios=[1, 2.4], constrained_layout=True
    )

    top.axhspan(0, 1, xmin=0, xmax=1, color="white")
    for label, index, colour in (
        ("development window", development, "#dfe7ef"),
        ("scored by the backtest", tested, "#bc4b51"),
        ("holdout — SEALED", holdout, "#8a8a8a"),
    ):
        top.barh(
            label,
            index.max() - index.min(),
            left=index.min(),
            color=colour,
            height=0.6,
            alpha=0.85 if colour == "#bc4b51" else 1.0,
        )
    top.set_xlim(development.min(), holdout.max())
    top.grid(axis="x", alpha=0.3)
    top.set_title(
        f"{len(tested)} of {len(development)} development days are scored; "
        f"{len(window['rows']):,} delivery hours in total",
        fontsize=10,
    )
    top.invert_yaxis()

    for i, fold in enumerate(folds):
        bottom.barh(
            i,
            fold.train_days.max() - fold.train_days.min(),
            left=fold.train_days.min(),
            color="#5b8e7d",
            height=0.72,
        )
        bottom.barh(
            i,
            fold.test_days.max() - fold.test_days.min(),
            left=fold.test_days.min(),
            color="#bc4b51",
            height=0.72,
        )
    bottom.set_xlim(development.min(), holdout.max())
    bottom.set_ylabel("fold")
    bottom.set_yticks(range(0, len(folds), 3))
    bottom.invert_yaxis()
    bottom.grid(axis="x", alpha=0.3)
    bottom.set_title(
        "Expanding train (green) · 7-day embargo · one month of test (red). "
        "No delivery day is tested twice.",
        fontsize=9.5,
    )
    bottom.axvline(holdout.min(), color="black", lw=1.2, ls=":")
    bottom.text(
        holdout.min(),
        1.0,
        "  holdout begins:\n  never fitted, never scored",
        fontsize=8,
        va="center",
    )
    return _save(fig, "evaluation_window")


#: Plain-language names for the chart axis. The code keys stay as they are.
DISPLAY_NAME = {
    "persistence": "Repeat what happened 48 h ago",
    "climatology": "Long-run average for this hour and season",
    "ridge_sanity_floor": "Straight line through 8 physics numbers",
    "physical_power_curve": "Turbine power curve, nothing learned",
    "lightgbm_point_monotone": "Boosted trees, single guess + error spread",
    "lightgbm_quantile": "Boosted trees, full range of outcomes",
    "A69_latest_vintage": "Grid operator's published forecast*",
}


def plot_leaderboard(runs: pd.DataFrame, capacity_mw: float = 4656.0) -> str:
    """How far each method is from the truth, in megawatts.

    One panel, in MW rather than capacity-factor units, because the question a reader
    asks first is "how wrong is it" and 0.0307 does not answer that. The bar lengths
    carry the magnitude and the printed values carry the precision, so no zoomed inset
    is needed.
    """
    frame = runs.iloc[::-1].copy()
    frame["miss_mw"] = frame.nmae * capacity_mw
    fig, ax = plt.subplots(figsize=(10, 3.6), constrained_layout=True)
    bars = ax.barh(
        [DISPLAY_NAME.get(n, n) for n in frame.name],
        frame.miss_mw,
        color=[COLOURS[n] for n in frame.name],
        height=0.68,
    )
    for bar, (_, row) in zip(bars, frame.iterrows(), strict=True):
        ax.text(
            row.miss_mw + 12,
            bar.get_y() + bar.get_height() / 2,
            f"{row.miss_mw:,.0f} MW",
            va="center",
            fontsize=9,
            fontweight="bold" if row["name"] == "lightgbm_quantile" else "normal",
        )
        if row["name"] == REFERENCE:
            bar.set_hatch("///")
            bar.set_edgecolor("white")
    ax.set_xlim(0, frame.miss_mw.max() * 1.18)
    ax.set_xlabel(
        "average miss, megawatts  —  against average output of 1,228 MW "
        f"and {capacity_mw:,.0f} MW installed"
    )
    ax.set_title(
        "SE3 onshore wind: how far each method lands from what actually happened",
        fontsize=10.5,
    )
    ax.grid(axis="x", alpha=0.3)
    ax.text(
        frame.miss_mw.max() * 0.30,
        0.15,
        "* published after the fact with later corrections folded in,\n"
        "  so it is a yardstick rather than a competitor",
        fontsize=8,
        style="italic",
        color="#333",
    )
    return _save(fig, "leaderboard_crps")


def plot_lead_curve(runs: pd.DataFrame) -> str:
    """Error against lead hour.

    The shape is not a gradient -- it is a step at lead 34, in every forecaster
    including the TSO benchmark. Two things change at that boundary at once: the NWP
    vintage switches from `previous_day1` to `previous_day2`, and the delivery day
    crosses from night into day. See reports/modelling.md.
    """
    fig, ax = plt.subplots(figsize=(9, 3.6), constrained_layout=True)
    for _, row in runs.iterrows():
        if row["name"] in {"persistence", "climatology"}:
            continue  # off-scale; they set the CRPS denominator, not the shape
        grid = run_artifact(row.run_uuid, "by_lead_hour").sort_values("lead_hour")
        ax.plot(
            grid.lead_hour,
            grid.nmae,
            label=row["name"],
            color=COLOURS[row["name"]],
            lw=1.7,
            ls="--" if row["name"] == REFERENCE else "-",
        )
    ax.axvline(VINTAGE_BOUNDARY - 0.5, color="black", lw=1.1, ls=":")
    ax.annotate(
        "lead 34: NWP vintage switches 1->2 days old\n"
        "AND the delivery day crosses into daylight",
        xy=(VINTAGE_BOUNDARY - 0.5, 0.0435),
        xytext=(35.2, 0.0455),
        fontsize=8,
        arrowprops={"arrowstyle": "->", "lw": 0.9},
    )
    ax.set_xlabel(
        "lead hour from the 00z run  (22 = 22:00 UTC on D, 46 = 22:00 UTC on D+1)"
    )
    ax.set_ylabel("nMAE")
    ax.set_ylim(0.005, 0.050)
    ax.set_title("A step, not a gradient", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=2, loc="lower right", framealpha=0.95)
    return _save(fig, "nmae_by_lead")


ABLATION = paths.INTERIM / "ablation_vintage.parquet"


def plot_vintage_ablation() -> str:
    """Separate the vintage switch from the day/night boundary at lead 34.

    Lead hour and clock hour are perfectly collinear under a fixed issue time, so the
    leaderboard alone cannot say which of the two causes the step. Forcing
    `nwp_offset_days = 2` onto *every* lead hour breaks the collinearity: leads 22-33
    then carry the stale vintage without moving in the day. Produced by
    `pipelines.ablate_vintage`.
    """
    grid = pd.read_parquet(ABLATION)
    grid = grid[grid.forecaster == "lightgbm_quantile"]
    fig, ax = plt.subplots(figsize=(9, 3.6), constrained_layout=True)
    styles = {
        "as_built": ("#bc4b51", "-", "as built: offset 1 where legal, 2 after"),
        "offset2_everywhere": ("#4f6d7a", "--", "ablation: offset 2 forced everywhere"),
    }
    for variant, (colour, dash, label) in styles.items():
        series = grid[grid.variant == variant].sort_values("lead_hour")
        ax.plot(
            series.lead_hour, series.nmae, color=colour, ls=dash, lw=1.8, label=label
        )
    ax.axvline(VINTAGE_BOUNDARY - 0.5, color="black", lw=1.1, ls=":")
    ax.annotate(
        "the two lines meet here, and stay met:\nthe back half already used offset 2",
        xy=(40, 0.0341),
        xytext=(34.2, 0.0280),
        fontsize=8,
        arrowprops={"arrowstyle": "->", "lw": 0.9},
    )
    ax.annotate(
        "forcing the stale vintage onto the front half\nraises its error ABOVE the back half's",
        xy=(27, 0.0386),
        xytext=(22.2, 0.0300),
        fontsize=8,
        arrowprops={"arrowstyle": "->", "lw": 0.9},
    )
    ax.set_xlabel("lead hour from the 00z run")
    ax.set_ylabel("nMAE")
    ax.set_title(
        "The step at lead 34 is the NWP vintage, not the day/night boundary",
        fontsize=10,
    )
    ax.grid(alpha=0.3)
    ax.legend(
        fontsize=8,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        ncol=2,
        frameon=False,
    )
    return _save(fig, "vintage_ablation")


#: Nested intervals drawn in every fan chart, widest first.
FAN_BANDS = ((0.05, 0.95), (0.10, 0.90), (0.25, 0.75))
FAN_ALPHA = (0.18, 0.28, 0.40)

BACKTEST = "backtest_{zone}_{fuel}.parquet"


def _market_hours(frame: pd.DataFrame) -> pd.Series:
    """Interval start times in market local time, plus the close of the last interval.

    Forecast rows are *intervals*, not instants. Plotting them as a line at their start
    times makes a 00:00-24:00 delivery day look like it stops at 23:00, so the series is
    extended by one step and drawn as stairs.
    """
    local = frame.valid_time.dt.tz_convert(MARKET_TZ)
    step = local.diff().dropna().min()
    return pd.concat([local, pd.Series([local.iloc[-1] + step])], ignore_index=True)


def _stairs(values: pd.Series) -> pd.Series:
    """Repeat the last value so a stairs plot closes its final interval."""
    return pd.concat([values, values.iloc[[-1]]], ignore_index=True)


def _fan(ax, frame: pd.DataFrame, prefix: str = "mw", colour: str = "#bc4b51") -> None:
    """Draw nested prediction intervals plus the median, as stairs in market time."""
    hours = _market_hours(frame)
    for (low, high), alpha in zip(FAN_BANDS, FAN_ALPHA, strict=True):
        ax.fill_between(
            hours,
            _stairs(frame[f"{prefix}_q{low:.2f}"]),
            _stairs(frame[f"{prefix}_q{high:.2f}"]),
            color=colour,
            alpha=alpha,
            linewidth=0,
            step="post",
            label=f"{low * 100:.0f}-{high * 100:.0f}% of outcomes",
        )
    ax.plot(
        hours,
        _stairs(frame[f"{prefix}_q0.50"]),
        color=colour,
        lw=1.8,
        drawstyle="steps-post",
        label="most likely",
    )


def _market_axis(ax, frame: pd.DataFrame) -> None:
    """Label the x axis by hour of the delivery day, not by timestamp."""
    hours = _market_hours(frame)
    ax.set_xlim(hours.iloc[0], hours.iloc[-1])
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3), tz=MARKET_TZ))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=MARKET_TZ))


def load_backtest(zone: str = "SE3", fuel: str = "wind_onshore") -> pd.DataFrame:
    """Per-row backtest forecasts, written by `pipelines.train`."""
    path = paths.PREDICTIONS / BACKTEST.format(zone=zone.lower(), fuel=fuel)
    if not path.exists():
        msg = f"{path} is missing; run pipelines.train to write it"
        raise FileNotFoundError(msg)
    return pd.read_parquet(path)


def pick_example_days(frame: pd.DataFrame, n: int = 4) -> list:
    """Choose delivery days that show the range of behaviour, not just the flattering.

    One day near the median daily error, one near the 90th percentile, the single worst
    day, and the windiest day in the scored window. Picking by rank rather than by hand
    keeps the selection honest and stable as the backtest is re-run.
    """
    daily = frame.groupby("delivery_day").apply(
        lambda g: pd.Series(
            {
                "mae": (g.cf - g["cf_q0.50"]).abs().mean(),
                "mean_cf": g.cf.mean(),
            }
        ),
        include_groups=False,
    )
    chosen = [
        (daily.mae.sub(daily.mae.median()).abs().idxmin(), "a typical day"),
        (
            daily.mae.sub(daily.mae.quantile(0.90)).abs().idxmin(),
            "a bad day — worse than 9 days in 10",
        ),
        (daily.mae.idxmax(), "the worst day in the whole period"),
        (daily.mean_cf.idxmax(), "the windiest day"),
    ]
    return chosen[:n]


def plot_backtest_examples(zone: str = "SE3", fuel: str = "wind_onshore") -> str:
    """What the backtest forecasts actually look like against the outturn.

    The leaderboard reduces 13,082 hours to eight numbers, which says nothing about
    whether a given day is forecast as a sensible shape. These are four delivery days
    picked by rank -- typical, bad, worst, windiest -- from the model that tops the
    board.
    """
    frame = load_backtest(zone, fuel)
    frame = frame[frame.forecaster == "lightgbm_quantile"].sort_values("valid_time")
    days = pick_example_days(frame)

    fig, axes = plt.subplots(2, 2, figsize=(11, 5.6), constrained_layout=True)
    for ax, (day, label) in zip(axes.ravel(), days, strict=True):
        panel = frame[frame.delivery_day == day]
        _fan(ax, panel)
        ax.plot(
            _market_hours(panel),
            _stairs(panel.cf * panel.capacity_mw),
            color="black",
            lw=1.8,
            ls="--",
            drawstyle="steps-post",
            label="what actually happened",
        )
        error = (panel.cf - panel["cf_q0.50"]).abs().mean() * panel.capacity_mw.mean()
        ax.set_title(
            f"{pd.Timestamp(day).date()} — {label}\naverage miss {error:,.0f} MW",
            fontsize=9,
        )
        ax.set_ylabel("MW")
        ax.grid(alpha=0.3)
        _market_axis(ax, panel)
        ax.tick_params(axis="x", labelsize=8)
    for ax in axes[1]:
        ax.set_xlabel("hour of the delivery day, market time (CET/CEST)")
    axes[0][0].legend(fontsize=7, ncol=2, loc="upper left")
    fig.suptitle(
        f"{zone} onshore wind — past forecasts against what actually happened",
        fontsize=10.5,
    )
    return _save(fig, "backtest_examples")


def plot_latest_forecast(zone: str = "SE3", fuel: str = "wind_onshore") -> str:  # noqa: ARG001
    """The operational forecast for a delivery day whose actuals do not exist yet.

    Written by `pipelines.predict`. There is nothing to score it against -- that is the
    point -- so the figure carries its issue time and model version instead, which is
    what makes the vintage auditable when the outturn does arrive.
    """
    from renewable_forecast.pipelines import predict

    frame = predict.latest(zone).sort_values("valid_time")
    day = pd.Timestamp(frame.delivery_day.iloc[0]).date()
    capacity = frame.capacity_mw.iloc[0]

    fig, ax = plt.subplots(figsize=(10, 3.8), constrained_layout=True)
    _fan(ax, frame, colour="#2a6f97")
    boundary = (
        frame[frame.lead_hour >= VINTAGE_BOUNDARY]
        .valid_time.min()
        .tz_convert(MARKET_TZ)
    )
    ax.axvline(boundary, color="black", lw=1.0, ls=":")
    ax.text(
        boundary,
        capacity * 0.02,
        "  from here on, the weather data is a day older",
        fontsize=8,
    )
    secondary = ax.secondary_yaxis(
        "right",
        functions=(lambda mw: 100 * mw / capacity, lambda pct: pct * capacity / 100),
    )
    secondary.set_ylabel("% of installed capacity")
    ax.set_ylim(0, max(frame["mw_q0.95"].max() * 1.15, capacity * 0.1))
    ax.set_ylabel("MW")
    ax.set_xlabel(f"{day}, market time (CET/CEST) — the traded day runs 00:00 to 24:00")
    ax.grid(alpha=0.3)
    _market_axis(ax, frame)
    ax.legend(fontsize=8, ncol=4, loc="upper right")
    issued_local = frame.issue_time.iloc[0].tz_convert(MARKET_TZ)
    ax.set_title(
        f"{zone} onshore wind, forecast for {day} — it has not happened yet\n"
        f"made {issued_local:%d %b %H:%M} market time, "
        f"{capacity:,.0f} MW installed · hourly, while the market now trades "
        "15-minute blocks",
        fontsize=9.5,
    )
    return _save(fig, "latest_forecast")


#: Capacity-factor buckets for the conditional-coverage breakdown.
CF_BUCKETS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

#: Below this many observations a bucket is anecdote, not evidence, and is drawn as
#: such. SE3 reached a capacity factor above 0.8 in five hours of the scored window.
MIN_BUCKET_N = 30


def coverage_by_output(zone: str = "SE3", fuel: str = "wind_onshore") -> pd.DataFrame:
    """Interval coverage and width as a function of how much the fleet is producing.

    Pooled coverage can be near nominal while the intervals fail systematically in one
    regime. This is the breakdown that exposes it, and it needs the per-row forecasts
    rather than the metric grid.
    """
    frame = load_backtest(zone, fuel)
    frame = frame[frame.forecaster == "lightgbm_quantile"]
    bucket = pd.cut(frame.cf, CF_BUCKETS)
    return (
        frame.assign(bucket=bucket)
        .groupby("bucket", observed=True)
        .apply(
            lambda g: pd.Series(
                {
                    "n": len(g),
                    "coverage_80": (
                        (g.cf >= g["cf_q0.10"]) & (g.cf <= g["cf_q0.90"])
                    ).mean(),
                    "coverage_90": (
                        (g.cf >= g["cf_q0.05"]) & (g.cf <= g["cf_q0.95"])
                    ).mean(),
                    "width_mw": (g["mw_q0.95"] - g["mw_q0.05"]).mean(),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )


def plot_coverage_by_output(zone: str = "SE3", fuel: str = "wind_onshore") -> str:
    """Where the intervals fail: coverage falls as output rises.

    The pooled coverage figures on the leaderboard average over this. Intervals are
    worst exactly where generation -- and therefore the MW error and the money -- is
    largest.
    """
    grid = coverage_by_output(zone, fuel)
    labels = [str(b) for b in grid.bucket]
    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 3.4), constrained_layout=True)

    solid = int((grid.n >= MIN_BUCKET_N).sum())
    for column, colour, marker, label in (
        ("coverage_90", "#bc4b51", "o", "observed 90%"),
        ("coverage_80", "#f4a259", "s", "observed 80%"),
    ):
        left.plot(
            labels[:solid],
            grid[column][:solid],
            marker=marker,
            color=colour,
            label=label,
        )
        if solid < len(grid):
            left.plot(
                labels[solid - 1 :],
                grid[column][solid - 1 :],
                marker=marker,
                color=colour,
                ls="--",
                alpha=0.45,
                markerfacecolor="white",
            )
    left.axhline(NOMINAL_90, color="#bc4b51", ls=":", lw=1.2)
    left.axhline(NOMINAL_80, color="#f4a259", ls=":", lw=1.2)
    left.set_ylim(0, 1.0)
    left.set_ylabel("interval coverage")
    left.set_xlabel("actual capacity factor")
    left.set_title("Coverage falls as output rises", fontsize=10)
    left.grid(alpha=0.3)
    left.legend(fontsize=7.5, loc="lower left")
    for x, (n, cov) in enumerate(zip(grid.n, grid.coverage_90, strict=True)):
        left.annotate(
            f"n={n:,.0f}" + ("\nanecdote" if n < MIN_BUCKET_N else ""),
            (x, cov),
            textcoords="offset points",
            xytext=(0, 8),
            fontsize=7,
            ha="center",
        )

    right.bar(labels, grid.width_mw, color="#5b8e7d", width=0.6)
    right.set_ylabel("mean p5-p95 width (MW)")
    right.set_xlabel("actual capacity factor")
    right.set_title("Intervals widen with output, but not enough", fontsize=10)
    right.grid(axis="y", alpha=0.3)
    fig.suptitle(
        "Conditional coverage — the pooled 0.852 at nominal 0.90 hides a monotone decline",
        fontsize=9.5,
    )
    return _save(fig, "coverage_by_output")


def plot_calibration(runs: pd.DataFrame) -> str:
    """PIT histograms and the coverage-vs-nominal curve -- where underdispersion shows."""
    named = runs.set_index("name")
    show = [
        n
        for n in (
            "lightgbm_quantile",
            "lightgbm_point_monotone",
            "physical_power_curve",
        )
        if n in named.index
    ]
    fig, axes = plt.subplots(
        1, len(show) + 1, figsize=(4 * (len(show) + 1), 3.2), constrained_layout=True
    )
    for ax, name in zip(axes, show, strict=False):
        pit = run_artifact(named.loc[name, "run_uuid"], "pit")["pit"]
        ax.hist(pit, bins=20, range=(0, 1), color=COLOURS[name], edgecolor="white")
        ax.axhline(len(pit) / 20, color="black", ls=":", lw=1.2)
        ax.set_title(f"{name}\nPIT", fontsize=9)
        ax.set_xlabel("PIT value")
        ax.set_yticks([])
    ax = axes[-1]
    ax.plot([0, 1], [0, 1], color="black", ls=":", lw=1.2, label="perfect")
    for name in show:
        row = named.loc[name]
        ax.plot(
            [NOMINAL_80, NOMINAL_90],
            [row.coverage_80, row.coverage_90],
            marker="o",
            ms=5,
            color=COLOURS[name],
            lw=1.6,
            label=name,
        )
    ax.legend(fontsize=7)
    ax.set_xlim(0.7, 1.0)
    ax.set_ylim(0.7, 1.0)
    ax.set_xlabel("nominal coverage")
    ax.set_ylabel("observed coverage")
    ax.set_title("Reliability\nbelow the line = too narrow", fontsize=9)
    ax.grid(alpha=0.3)
    fig.suptitle(
        "A flat PIT histogram means calibrated. U-shaped means the intervals are "
        "too narrow — mass piles up at both ends because the truth keeps landing "
        "outside them.",
        fontsize=9.5,
    )
    return _save(fig, "calibration")


def plot_seasonal(runs: pd.DataFrame) -> str:
    """Seasonal error and bias for the best model -- the icing signature."""
    row = runs[runs.name == "lightgbm_quantile"].iloc[0]
    grid = run_artifact(row.run_uuid, "by_season")
    order = ["DJF", "MAM", "JJA", "SON"]
    grid = grid.set_index("season").loc[order].reset_index()
    fig, (left, right) = plt.subplots(1, 2, figsize=(9.5, 3.2), constrained_layout=True)
    left.bar(grid.season, grid.nmae, color="#bc4b51", width=0.6)
    left.set_ylabel("nMAE")
    left.set_title("Winter is the hard season", fontsize=10)
    left.grid(axis="y", alpha=0.3)
    colours = ["#2a6f97" if v < 0 else "#d68c45" for v in grid.nbias]
    right.bar(grid.season, grid.nbias, color=colours, width=0.6)
    right.axhline(0, color="black", lw=1)
    right.set_ylabel("nBIAS  (actual minus predicted)")
    right.set_title("...and DJF is where the model over-predicts", fontsize=10)
    right.grid(axis="y", alpha=0.3)
    right.annotate(
        "negative = forecast says windy,\nfleet delivers less (icing)",
        xy=(0, grid.nbias.iloc[0]),
        xytext=(0.55, -0.011),
        fontsize=7.5,
        arrowprops={"arrowstyle": "->", "lw": 0.8},
    )
    return _save(fig, "seasonal_bias")


def plot_capacity_ceiling() -> str:
    """The denominator diagnostic: a flat high-percentile CF means capacity is right."""
    target = pd.read_parquet(paths.INTERIM / "targets_se3_wind_onshore.parquet")
    target = target.set_index("period_start").sort_index()
    ceiling = target["cf"].rolling("90D").quantile(0.999)
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(9, 4.4), sharex=True, height_ratios=[2, 1]
    )
    top.plot(ceiling.index, ceiling.to_numpy(), color="#2a6f97", lw=1.2)
    top.axhspan(0.90, 1.00, color="#8cb369", alpha=0.18)
    top.set_ylim(0.6, 1.1)
    top.set_ylabel("rolling 90-day p99.9 of CF")
    top.set_title(
        "Capacity denominator check — a flat line in the green band means the "
        "denominator tracks the fleet",
        fontsize=10,
    )
    top.grid(alpha=0.3)
    bottom.plot(target.index, target["capacity_mw"].to_numpy(), color="#5b8e7d", lw=1.2)
    bottom.set_ylabel("installed MW")
    bottom.grid(alpha=0.3)
    return _save(fig, "capacity_ceiling")


def ceiling_by_year() -> pd.DataFrame:
    """Yearly p99.9 of implied capacity factor per Swedish zone.

    Recomputed here rather than read from the audit table so the figure and the audit
    cannot disagree. See `pipelines.data_audit.check_g_capacity` for the same statistic.
    """
    from renewable_forecast.sources import entsoe, fleet

    turbines = fleet.load_turbines()
    generation = entsoe.load("actual_generation")
    out = {}
    for zone in ("SE1", "SE2", "SE3", "SE4"):
        series = generation[
            (generation.zone == zone) & (generation.fuel_type == "Wind Onshore")
        ]
        if series.empty:
            continue
        capacity = fleet.capacity_series(turbines, zone).set_index("date").capacity_mw
        observed = series.set_index("period_start").value_mw.sort_index()
        daily = capacity.reindex(
            observed.index.tz_convert("UTC").tz_localize(None).normalize()
        ).to_numpy()
        factor = pd.Series(observed.to_numpy() / daily, index=observed.index)
        out[zone] = factor.groupby(factor.index.year).quantile(0.999)
    return pd.DataFrame(out)


def plot_ceiling_drift() -> str:
    """The denominator diagnostic across all four Swedish zones.

    The plan's assertion is that this line stays flat. It does not: every zone drifts
    down together, which rules out a per-zone boundary error and leaves either a
    numerator that under-reports a growing fleet or a denominator that over-counts.
    """
    grid = ceiling_by_year()
    grid = grid[(grid.index >= 2018) & (grid.index <= 2025)]
    fig, ax = plt.subplots(figsize=(7.5, 3.4), constrained_layout=True)
    for zone in grid.columns:
        ax.plot(
            grid.index,
            grid[zone],
            marker="o",
            ms=4,
            lw=1.6,
            label=zone,
            color="#bc4b51" if zone == "SE3" else None,
            zorder=3 if zone == "SE3" else 2,
        )
    ax.axhspan(0.90, 1.00, color="#8cb369", alpha=0.18)
    ax.text(2018.05, 1.02, "expected band if the denominator is right", fontsize=7.5)
    ax.set_ylim(0.65, 1.12)
    ax.set_ylabel("p99.9 of implied CF")
    ax.set_title(
        "Open finding: the capacity ceiling drifts down in every zone at once",
        fontsize=10,
    )
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=4)
    return _save(fig, "ceiling_drift")


def plot_horizon() -> str:
    """The task in time, in market local time, with no jargon.

    Drawn on the market clock rather than on forecast lead hours, because this is the
    first figure a reader meets. The lead-hour framing every other chart uses is set out
    in `docs/metrics.md`; the mapping is that market midnight on the delivery day is
    +23 h from the overnight weather run under CET.
    """
    fig, ax = plt.subplots(figsize=(10.5, 3.0), constrained_layout=True)

    ax.axvspan(-2, 10, color="#e8eef4", label="what we already know when we forecast")
    ax.axvspan(24, 48, color="#bc4b51", alpha=0.28, label="the day we are forecasting")
    ax.axvspan(
        6.75,
        8.6,
        color="#5b8e7d",
        alpha=0.55,
        label="when the weather results actually land",
    )

    ax.axvline(1, color="#555", lw=1.1, ls="--")
    ax.axvline(10, color="black", lw=2.0)
    ax.axvline(12, color="#1d4e6b", lw=1.6, ls="-.")

    for x, y, text in (
        (1, 0.80, "overnight weather\nmodel starts running"),
        (7.7, 0.52, "results\nland here"),
        (10, 0.66, "we make\nour forecast"),
        (12, 0.36, "bidding closes\nfor tomorrow"),
    ):
        ax.annotate(
            text,
            xy=(x, y - 0.12),
            xytext=(x, y),
            fontsize=8.5,
            ha="center",
            va="bottom",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 1.5},
            arrowprops={"arrowstyle": "-", "lw": 0.8, "color": "#555"},
        )

    ax.annotate(
        "",
        xy=(24, 0.18),
        xytext=(12, 0.18),
        arrowprops={"arrowstyle": "<->", "lw": 1.2, "color": "#1d4e6b"},
    )
    ax.annotate(
        "",
        xy=(48, 0.08),
        xytext=(12, 0.08),
        arrowprops={"arrowstyle": "<->", "lw": 1.2, "color": "#1d4e6b"},
    )
    ax.text(17.5, 0.205, "12 hours ahead", fontsize=8, color="#1d4e6b", ha="center")
    ax.text(30, 0.105, "36 hours ahead", fontsize=8, color="#1d4e6b", ha="center")

    ax.set_xlim(-2, 50)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xticks([0, 6, 12, 18, 24, 30, 36, 42, 48])
    ax.set_xticklabels(
        [
            "00:00",
            "06:00",
            "12:00",
            "18:00",
            "00:00",
            "06:00",
            "12:00",
            "18:00",
            "24:00",
        ]
    )
    ax.set_xlabel("market time (CET/CEST)", fontsize=9)
    ax.text(
        11, -0.19, "today", fontsize=9, ha="center", transform=ax.get_xaxis_transform()
    )
    ax.text(
        36,
        -0.19,
        "tomorrow — the traded day",
        fontsize=9,
        ha="center",
        transform=ax.get_xaxis_transform(),
    )
    ax.legend(fontsize=8.5, loc="upper right", framealpha=0.95, ncol=1)
    ax.set_title(
        "Every morning we forecast tomorrow, before bidding closes at midday",
        fontsize=10.5,
    )
    return _save(fig, "task_horizon")


def plot_pinball(runs: pd.DataFrame) -> str:
    """Pinball loss per quantile level -- which part of the distribution is weak."""
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    for _, row in runs.iterrows():
        if row["name"] in {"persistence", "climatology"}:
            continue
        grid = run_artifact(row.run_uuid, "pinball_by_level").sort_values("level")
        ax.plot(
            grid.level,
            grid.pinball,
            label=row["name"],
            color=COLOURS[row["name"]],
            lw=1.6,
            ls="--" if row["name"] == REFERENCE else "-",
        )
    ax.set_xlabel("quantile level")
    ax.set_ylabel("pinball loss")
    ax.set_title("Loss is worst in the middle of the distribution", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    return _save(fig, "pinball_by_level")


def build() -> list[str]:
    """Regenerate every report figure. Returns the filenames written."""
    runs = latest_runs()
    return [
        plot_horizon(),
        plot_evaluation_window(),
        plot_leaderboard(runs),
        plot_lead_curve(runs),
        plot_vintage_ablation(),
        plot_backtest_examples(),
        plot_coverage_by_output(),
        plot_latest_forecast(),
        plot_calibration(runs),
        plot_seasonal(runs),
        plot_pinball(runs),
        plot_capacity_ceiling(),
        plot_ceiling_drift(),
    ]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in build():
        logger.info("figure: %s", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
