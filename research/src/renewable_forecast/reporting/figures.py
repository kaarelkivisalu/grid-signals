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
import matplotlib.pyplot as plt
import pandas as pd

from renewable_forecast import paths

logger = logging.getLogger(__name__)

FIGURES = paths.REPORTS / "figures"
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


def plot_leaderboard(runs: pd.DataFrame) -> str:
    """CRPS per forecaster.

    Two panels because one axis cannot show both facts: the learned models beat the
    naive baselines by an order of magnitude, and they beat the physical baseline by
    15%. The left panel is the gap that matters for "does this work at all"; the right
    is the gap that matters for "was the machine learning worth it".
    """
    frame = runs.iloc[::-1]
    fig, (wide, zoom) = plt.subplots(
        1, 2, figsize=(12.5, 3.4), width_ratios=[1.25, 1], constrained_layout=True
    )
    bars = wide.barh(
        frame.name, frame.crps, color=[COLOURS[n] for n in frame.name], height=0.68
    )
    for bar, (_, row) in zip(bars, frame.iterrows(), strict=True):
        wide.text(
            row.crps + 0.004,
            bar.get_y() + bar.get_height() / 2,
            f"{row.crps:.4f}",
            va="center",
            fontsize=8.5,
        )
        if row["name"] == REFERENCE:
            bar.set_hatch("///")
            bar.set_edgecolor("white")
    wide.set_xlim(0, 0.175)
    wide.set_xlabel("CRPS (capacity-normalised) — lower is better")
    wide.set_title("All forecasters", fontsize=10)
    wide.grid(axis="x", alpha=0.3)

    close = frame[~frame.name.isin({"persistence", "climatology", REFERENCE})]
    bars = zoom.barh(
        close.name, close.crps, color=[COLOURS[n] for n in close.name], height=0.6
    )
    for bar, (_, row) in zip(bars, close.iterrows(), strict=True):
        zoom.text(
            row.crps + 0.0004,
            bar.get_y() + bar.get_height() / 2,
            f"{row.crps:.4f}",
            va="center",
            fontsize=8.5,
        )
    zoom.set_xlim(0, 0.033)
    zoom.set_xlabel("CRPS")
    zoom.set_title("The models that are actually close", fontsize=10)
    zoom.grid(axis="x", alpha=0.3)
    fig.suptitle(
        "SE3 wind, development set — A69 (hatched) is served at its latest revision "
        "and is a reference, not a bar",
        fontsize=9.5,
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
    """The task in time: what is known at 09:00 UTC and what is being predicted."""
    fig, ax = plt.subplots(figsize=(9.5, 2.4))
    ax.axvspan(-48, 0, color="#dfe7ef", label="known: actuals, NWP runs")
    ax.axvspan(22, 47, color="#bc4b51", alpha=0.30, label="predicted: delivery day D+1")
    ax.axvspan(0, 22, color="#f2f2f2")
    ax.axvline(0, color="black", lw=1.6)
    ax.annotate(
        "issue 09:00 UTC",
        xy=(0, 0.78),
        xytext=(-20, 0.86),
        fontsize=8.5,
        arrowprops={"arrowstyle": "->", "lw": 0.9},
    )
    ax.annotate(
        "00z NWP run\n(9 h before issue)",
        xy=(-9, 0.30),
        xytext=(-45, 0.16),
        fontsize=8,
        arrowprops={"arrowstyle": "->", "lw": 0.9},
    )
    ax.annotate(
        "gate closure 12:00 local\n(10:00 UTC in summer)",
        xy=(1, 0.30),
        xytext=(3, 0.12),
        fontsize=8,
        arrowprops={"arrowstyle": "->", "lw": 0.9},
    )
    ax.axvline(-9, color="#444", lw=1.0, ls="--")
    ax.set_xlim(-50, 50)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xlabel("hours relative to issue time")
    ax.set_xticks([-48, -24, -9, 0, 22, 47])
    ax.legend(fontsize=8, loc="upper right", framealpha=0.95)
    ax.set_title("The forecasting task in time", fontsize=10)
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
        plot_leaderboard(runs),
        plot_lead_curve(runs),
        plot_vintage_ablation(),
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
