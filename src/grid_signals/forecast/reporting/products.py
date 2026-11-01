"""Publish the quarter-hour development tables and the latest forecast fan charts."""

import json
from datetime import UTC, datetime

import pandas as pd

from grid_signals.forecast import paths
from grid_signals.forecast.pipelines import predict
from grid_signals.forecast.reporting import figures


def _table(frame: pd.DataFrame, columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in frame[columns].itertuples(index=False, name=None):
        values = [
            f"{value:.5f}" if isinstance(value, float) else str(value) for value in row
        ]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write() -> str:
    """Generate the report from scored outputs, never from transcribed numbers."""
    lines = [
        "# Quarter-hour wind and solar products",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. Development evaluation only; the sealed holdout has not been scored.",
        "",
        "The added protocol fixes three monthly folds: December 2025, January 2026 and February 2026, with a seven-day embargo. Arms within each task use identical complete delivery days and genuine 15-minute observations. Counts can differ between tasks because their weather and observation coverage differ.",
        "",
        "Both wind arms include the information-age correction for forward weather trajectory terms (+3 h). The September hourly board predates this correction and is historical evidence, not the accuracy of the corrected current code. Solar dates its irradiance interpolation to the following hourly endpoint.",
        "",
    ]
    for fuel, title in (
        ("wind_onshore", "SE3 wind, hourly-trained Stage 1"),
        ("solar", "DE-LU solar, native quarter-hour training"),
    ):
        table = pd.read_parquet(paths.INTERIM / f"products_15min_{fuel}.parquet")
        lines.extend([f"## {title}", ""])
        if fuel == "solar":
            lines.extend(
                [
                    "Headline metrics exclude night: midpoint solar elevation must exceed 5° at at least one declared site. Capacity factors use the last annual A68 snapshot preceding issue, not a future year-end anchor. A dated MaStR denominator and fleet are still pending.",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "Both arms use the same hourly-trained model. The reference repeats each hourly distribution four times; the candidate interpolates weather within each vintage before computing power-curve features. Repeated hourly distributions are the operational default: interpolation did not demonstrate a marginal CRPS gain in this A/B. Its mean CRPS is slightly higher, but the paired difference is not statistically resolved. It improves ramp MAE while worsening peak-ramp timing. Interpolation remains available with `predict --wind-method interpolate`. Neither method supplies native sub-hourly NWP skill.",
                    "",
                ]
            )
        lines.extend(
            [
                _table(
                    table,
                    [
                        "name",
                        "days",
                        "scored_intervals",
                        "nmae",
                        "crps",
                        "coverage_80",
                        "coverage_90",
                    ],
                ),
                "",
                _table(
                    table,
                    [
                        "name",
                        "crps_delta_ci_low",
                        "crps_delta_ci_high",
                        "ramp_mae_cf",
                        "peak_ramp_timing_mae_min",
                    ],
                ),
                "",
            ]
        )
        reference = "clear-sky climatology" if fuel == "solar" else "hourly repeated"
        lines.extend(
            [
                f"CRPS differences are against {reference}, with paired 95% day-block bootstrap intervals. Negative differences favour the named model. Ramp MAE is in capacity-factor changes per quarter-hour; timing error is in minutes for the largest absolute daily median ramp. Marginal quantiles do not describe joint ramp uncertainty.",
                "",
            ]
        )
    lines.extend(
        [
            "## Operational output",
            "",
            "Forecasts contain 19 non-crossing quantiles in CF and MW, with zone, fuel, resolution, issue time, interval start/end, assumed capacity and model version. Local delivery days contain 92, 96 or 100 quarter-hours across DST. Archive appends are locked and atomic; readers filter by task. Production fitting uses observations from days ending before issue day and may use past holdout observations without scoring them.",
            "",
        ]
    )
    for zone, fuel in (("SE3", "wind_onshore"), ("DE_LU", "solar")):
        frame = predict.latest(zone, fuel, "15min")
        path = figures.plot_latest_forecast(zone, fuel, "15min")
        lines.extend(
            [
                f"### {zone} {fuel}",
                "",
                f"Delivery {frame.delivery_day.iloc[0]:%Y-%m-%d}; {len(frame)} intervals; issue {frame.issue_time.iloc[0]:%Y-%m-%d %H:%M UTC}; method `{frame.temporal_method.iloc[0]}`; capacity assumption {frame.capacity_mw.iloc[0]:,.2f} MW; version `{frame.model_version.iloc[0]}`.",
                "",
                f"![](figures/{path})",
                "",
            ]
        )
    manifest_path = paths.INTERIM / "weather_archive_status.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        rows = [
            {
                "source": name,
                "available_runs": source["available"],
                "missing_runs": len(source["missing"]),
                "latest_run": source["latest"],
            }
            for name, source in manifest["sources"].items()
        ]
        lines.extend(
            [
                "## Archive refresh",
                "",
                f"Run-file coverage for {manifest['start']} → {manifest['end_exclusive']} (exclusive), checked {manifest['checked_at']}. Unavailable future cycles are excluded. Full missing-date lists are in `data/interim/weather_archive_status.json`.",
                "",
                _table(
                    pd.DataFrame(rows),
                    ["source", "available_runs", "missing_runs", "latest_run"],
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Limits and remaining validation",
            "",
            "The solar fleet is an equal-area six-site lattice with a fixed south/east/west orientation mix and nominal thermal/loss assumptions. It is a working first forecast, not a registry-weighted PV model. Its annual capacity snapshots lack publication vintages. Radiation comes from one pinned ECMWF model in the whole-day Previous Runs archive; solar IFS HRES single-run features are not yet implemented. Clear-sky-index interpolation approximates midpoint interval output and cannot resolve unobserved sub-hourly clouds. Missing weather remains missing rather than becoming zero sunshine.",
            "",
            "Calibration is measured, not assumed to transfer from wind. Read nominal 80% and 90% coverage against their observed values above. Night-time solar quantiles are set to zero after calibration. Native quarter-hour wind training, joint-path energy/variogram scoring, the sealed holdout evaluation and a scheduled live trial remain separate work. These outputs are standalone research artifacts; the grid-signals integration contract still applies.",
            "",
            "Method references: [Open-Meteo Previous Runs](https://open-meteo.com/en/docs/previous-runs-api) and [pvlib plane-of-array irradiance](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.get_total_irradiance.html). Solar requests explicitly use instantaneous radiation so the provider's backwards-hour-mean convention cannot shift the target labels. See the protocol amendment for all evaluation choices.",
            "",
            "## Reproduce",
            "",
            "```bash",
            "export PYTHONPATH=research/src",
            "uv run --group research python -m grid_signals.forecast.pipelines.refresh_archives 2026-03-01 2026-10-16",
            "uv run --group research python -m grid_signals.forecast.pipelines.pull_solar 2024-03-06 2026-10-18",
            "uv run --group research python -m grid_signals.forecast.pipelines.pull_actuals 2026-09-19 2026-10-16",
            "uv run --group research python -m grid_signals.forecast.pipelines.backtest_products --fuel wind_onshore",
            "uv run --group research python -m grid_signals.forecast.pipelines.backtest_products --fuel solar",
            "uv run --group research python -m grid_signals.forecast.pipelines.predict --resolution 15min",
            "uv run --group research python -m grid_signals.forecast.pipelines.predict --fuel solar --resolution 15min",
            "uv run --group research python -m grid_signals.forecast.reporting.products",
            "```",
            "",
        ]
    )
    report = paths.REPORTS / "products_15min.md"
    report.write_text("\n".join(lines))
    return str(report)


if __name__ == "__main__":
    print(write())
