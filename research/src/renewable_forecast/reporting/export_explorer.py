"""Export full, already evaluated series for the local market/benchmark explorer.

No fitting or model selection. CRPS contributions use the original 19 quantiles;
plots retain seven. Actuals in a backtest remain its original scoring targets.
Content-addressed Parquet files are written before the manifest is replaced.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import scoringrules as sr

from renewable_forecast import paths

DEFAULT_OUTPUT = paths.ROOT.parent / "src/grid_signals/app/assets/explorer"
LEVELS = np.arange(1, 20) / 20
DISPLAY_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
START = pd.Timestamp("2025-11-30T00:00Z")


def normalise_backtest(frame: pd.DataFrame, target: str, split: str) -> pd.DataFrame:
    """Keep native units and per-interval scores; unify signed error to forecast-actual."""
    frame = frame.sort_values("valid_time").copy()
    renewable = target in {"solar", "wind_onshore"}
    actual = frame.cf.to_numpy() if renewable else frame[target].to_numpy()
    quantiles = frame[[f"q{level:.2f}" for level in LEVELS]].to_numpy()
    if not np.isfinite(quantiles).all() or not np.isfinite(actual).all():
        raise ValueError("non-finite evaluated predictions")
    if (np.diff(quantiles, axis=1) < -1e-8).any():
        raise ValueError("crossing evaluated quantiles")
    scale = frame.capacity_mw.to_numpy() if renewable else np.ones(len(frame))
    signed = quantiles[:, 9] - actual
    loss = sr.crps_quantile(actual, quantiles, LEVELS)
    model = frame.forecaster.replace(
        {"quantile": "solar_quantile" if target == "solar" else "hourly_repeated"}
    )
    result = pd.DataFrame(
        {
            "valid_time": pd.to_datetime(frame.valid_time, utc=True),
            "delivery_date": pd.to_datetime(frame.delivery_day).dt.strftime("%Y-%m-%d"),
            "target": target,
            "model": model,
            "split": split,
            "actual": actual * scale,
            "eligible": frame.daylight.to_numpy() if renewable else True,
            "capacity_mw": scale if renewable else np.nan,
            "mae": abs(signed) * scale,
            "squared_error": signed**2 * scale**2,
            "bias": signed * scale,
            "crps": loss * scale,
            "mae_capacity": abs(signed) if renewable else np.nan,
            "crps_capacity": loss if renewable else np.nan,
            "bias_capacity": signed if renewable else np.nan,
            "coverage_80": (actual >= quantiles[:, 1]) & (actual <= quantiles[:, 17]),
            "coverage_90": (actual >= quantiles[:, 0]) & (actual <= quantiles[:, 18]),
        },
        index=frame.index,
    )
    for level in DISPLAY_LEVELS:
        result[f"q{level:.2f}"] = frame[f"q{level:.2f}"].to_numpy() * scale
    if result.duplicated(["target", "model", "split", "valid_time"]).any():
        raise ValueError("duplicate evaluated intervals")
    return result.reset_index(drop=True)


def expand_native(series: pd.Series) -> pd.DataFrame:
    """Project interval-average power to 15 min without bridging missing source slots.

    Infer the native cadence independently per UTC day; a missing hourly slot is
    left empty. Values are repeated over their own interval, never interpolated.
    """
    series = series.sort_index().dropna()
    if series.index.has_duplicates:
        raise ValueError("duplicate observation timestamps")
    parts = []
    next_times = series.index.to_series().shift(-1)
    for _, group in series.groupby(series.index.floor("D")):
        differences = group.index.to_series().diff().dt.total_seconds().div(60)
        steps = differences[differences.isin([15, 30, 60])]
        if steps.empty:
            continue
        step = int(steps.mode().iloc[0])
        for offset in range(0, step, 15):
            part = pd.DataFrame(
                {"value": group.to_numpy(), "step_minutes": step},
                index=group.index + pd.Timedelta(minutes=offset),
            )
            next_group = next_times.reindex(group.index)
            keep = next_group.isna().to_numpy() | (
                part.index < pd.DatetimeIndex(next_group)
            )
            parts.append(part.loc[keep])
    if not parts:
        return pd.DataFrame(columns=["value", "step_minutes"])
    result = pd.concat(parts).sort_index()
    if result.index.has_duplicates:
        raise ValueError("overlapping source intervals")
    return result


def _observations(data: Path, zone: str, sources: set[Path]) -> pd.DataFrame:
    columns = {}

    def add(name: str, series: pd.Series) -> None:
        expanded = expand_native(series)
        columns[name] = expanded.value
        columns[f"{name}_step_minutes"] = expanded.step_minutes

    root = data / "raw/entsoe"
    for dataset in ("actual_generation", "day_ahead_prices", "actual_load"):
        files = list((root / f"dataset={dataset}" / f"zone={zone}").glob("*.parquet"))
        if not files:
            continue
        time = "valid_time" if dataset == "actual_load" else "period_start"
        frames = [pd.read_parquet(p, filters=[(time, ">=", START)]) for p in files]
        sources.update(files)
        frame = pd.concat(frames, ignore_index=True)
        if frame.empty:
            continue
        frame = frame.sort_values("fetched_at")
        if dataset == "actual_generation":
            frame = frame[frame.aggregation == "Actual Aggregated"]
            for name, fuel in (
                ("solar", "Solar"),
                ("wind_onshore", "Wind Onshore"),
                ("wind_offshore", "Wind Offshore"),
            ):
                rows = frame[frame.fuel_type == fuel].drop_duplicates(time, keep="last")
                if not rows.empty:
                    add(name, rows.set_index(time).value_mw)
        else:
            name = "load" if dataset == "actual_load" else "price"
            value = "mw" if dataset == "actual_load" else "value_mw"
            add(name, frame.drop_duplicates(time, keep="last").set_index(time)[value])
    for file in (data / "market_context").glob(f"{zone}_*.parquet"):
        frame = pd.read_parquet(file)
        sources.add(file)
        for column in frame.columns.difference(["fetched_at"]):
            add(column, frame[column])
    if not columns:
        return pd.DataFrame()
    result = pd.DataFrame(columns).sort_index()
    result.index.name = "valid_time"
    # Missing offshore data is not silently treated as zero generation.
    components = ["load", "solar", "wind_onshore", "wind_offshore"]
    if all(column in result for column in components):
        result["residual_load"] = result.load - result[components[1:]].sum(
            axis=1, min_count=3
        )
    return result.reset_index()


def _published(data: Path) -> dict[str, list[pd.DataFrame]]:
    output = {}
    for filename, target, prefix, default in (
        ("forecast_vintages", None, "mw_q", None),
        ("price_vintages", "price", "eur_mwh_q", "lightgbm_quantile"),
        ("load_vintages", "load", "mw_q", "load_quantile_gbm"),
    ):
        file = data / f"predictions/{filename}.parquet"
        if not file.exists():
            continue
        frame = pd.read_parquet(file)
        # Legacy rows lack immutable publication evidence; retain them in the
        # original archive rather than suggesting they were timely forecasts.
        frame = frame[frame.forecast_id.notna()].copy()
        if filename == "forecast_vintages":
            frame = frame[frame.resolution == "15min"].copy()
            frame["target"] = frame.fuel_type
            frame["model"] = frame.fuel_type.map(
                {"solar": "solar_quantile", "wind_onshore": "hourly_repeated"}
            )
        else:
            frame["target"] = target
            frame["model"] = frame.get(
                "forecaster", pd.Series(index=frame.index, dtype=str)
            ).fillna(default)
        frame["delivery_date"] = pd.to_datetime(frame.delivery_day).dt.strftime(
            "%Y-%m-%d"
        )
        frame["split"] = "Published archive"
        frame["actual"] = np.nan
        frame["eligible"] = False  # Live scoring remains the immutable issue scorecard.
        for level in DISPLAY_LEVELS:
            frame[f"q{level:.2f}"] = frame[f"{prefix}{level:.2f}"]
        columns = [
            "valid_time",
            "delivery_date",
            "target",
            "model",
            "split",
            "actual",
            "eligible",
            *[f"q{level:.2f}" for level in DISPLAY_LEVELS],
            "forecast_id",
            "publication_status",
            "published_at",
            "information_cutoff_at",
            "model_version",
        ]
        for zone, rows in frame.groupby("zone"):
            output.setdefault(zone, []).append(rows[columns])
    return output


def write(data: Path = paths.DATA, output: Path = DEFAULT_OUTPUT) -> dict:
    """Export a consistent generation, then atomically switch the manifest."""
    output.mkdir(parents=True, exist_ok=True)
    sources: set[Path] = set()
    forecast_parts = _published(data)
    for zone, target, filename in (
        ("SE3", "wind_onshore", "backtest_15min_wind_onshore"),
        ("DE_LU", "solar", "backtest_15min_solar"),
        ("DE_LU", "price", "backtest_price"),
        ("DE_LU", "load", "backtest_load"),
    ):
        file = data / f"predictions/{filename}.parquet"
        if file.exists():
            sources.add(file)
            forecast_parts.setdefault(zone, []).append(
                normalise_backtest(pd.read_parquet(file), target, "Development")
            )
        if target in {"solar", "wind_onshore"}:
            files = sorted(
                (data / "holdout_renewables_2026_10_15").glob(f"{target}_*.parquet")
            )
            release = data / "holdout_renewables_2026_10_15/result.json"
        else:
            release = data / f"holdout_{target}_2026_10_15/result.json"
            candidate = release.parent / "predictions.parquet"
            files = [candidate] if candidate.exists() else []
        # Completed release only: never open an unscored/sealed evaluation.
        if (
            files
            and release.exists()
            and json.loads(release.read_text()).get("completed_at")
        ):
            sources.update([release, *files])
            final = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
            forecast_parts.setdefault(zone, []).append(
                normalise_backtest(final, target, "Final holdout")
            )
    zones = set(forecast_parts) | {"SE1", "SE2", "SE4"}
    zones.update(
        file.name.split("_")[0] for file in (data / "market_context").glob("*.parquet")
    )
    manifest = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "zones": {},
    }

    def artifact(frame: pd.DataFrame, name: str) -> str:
        raw = frame.to_parquet(index=False, compression="zstd")
        filename = f"{name}-{hashlib.sha256(raw).hexdigest()[:16]}.parquet"
        temporary = output / f"{filename}.tmp"
        temporary.write_bytes(raw)
        temporary.replace(output / filename)
        return filename

    for zone in sorted(zones):
        observed = _observations(data, zone, sources)
        forecasts = (
            pd.concat(forecast_parts[zone], ignore_index=True)
            if zone in forecast_parts
            else pd.DataFrame()
        )
        info = {
            "observation_file": None,
            "forecast_file": None,
            "targets": {},
            "dates": [],
        }
        dates = set()
        if not observed.empty:
            info["observation_file"] = artifact(observed, f"{zone}-observations")
            # Market timezones differ; use the app's registry only for metadata.
            from grid_signals.app.markets import BY_CODE

            local_days = observed.valid_time.dt.tz_convert(
                BY_CODE[zone].timezone
            ).dt.strftime("%Y-%m-%d")
            dates.update(local_days)
            info["observations"] = {
                col: {
                    "intervals": int(observed[col].notna().sum()),
                    "start": local_days[observed[col].notna()].min(),
                    "end": local_days[observed[col].notna()].max(),
                }
                for col in observed
                if col != "valid_time"
                and not col.endswith("_step_minutes")
                and observed[col].notna().any()
            }
        if not forecasts.empty:
            forecasts["valid_time"] = pd.to_datetime(forecasts.valid_time, utc=True)
            info["forecast_file"] = artifact(forecasts, f"{zone}-forecasts")
            dates.update(forecasts.delivery_date)
            info["targets"] = {
                target: {
                    "models": sorted(rows.model.unique()),
                    "splits": sorted(rows.split.unique()),
                    "dates": sorted(rows.delivery_date.unique()),
                    "dates_by_split": {
                        split: sorted(part.delivery_date.unique())
                        for split, part in rows.groupby("split")
                    },
                }
                for target, rows in forecasts.groupby("target")
            }
        info["dates"] = sorted(dates)
        manifest["zones"][zone] = info
    sources.update((data / "predictions").glob("*vintages.parquet"))
    manifest["sources"] = [
        {
            "path": str(p.relative_to(data)),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(sources)
    ]
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(output / "manifest.json")
    referenced = {
        info[key]
        for info in manifest["zones"].values()
        for key in ("forecast_file", "observation_file")
    }
    # Previous-generation files may be in use by a running reader; keep them until
    # the next explicit cleanup/deploy. Do not unlink during an active session.
    return {"zones": len(manifest["zones"]), "files": len(referenced - {None})}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(write(output=args.output))
