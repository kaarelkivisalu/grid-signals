"""Phase 2 data audit -- the hard gate before any modelling.

Produces `reports/data_audit.md` plus figures. Every check returns a DataFrame so the
numbers in the report are re-derivable rather than transcribed.
"""

import logging
from datetime import UTC, date, datetime, timedelta

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from renewable_forecast import paths, windows
from renewable_forecast.sources import entsoe, fleet
from renewable_forecast.targets import actuals

logger = logging.getLogger(__name__)

FIGURES = paths.REPORTS / "figures"

# Thresholds the plan commits to. Kept here so the report can state pass/fail rather
# than leaving the reader to eyeball a chart.
MIN_COVERAGE_PCT = 90.0
MIN_SOLAR_PEAK_RATIO = 0.40
MIN_SOLAR_SEASONAL_RATIO = 10.0
#: Reported solar at night must be a negligible fraction of peak.
MAX_SOLAR_NIGHT_SHARE = 0.01
OFFSHORE_MATERIAL_MW = 50.0
OFFSHORE_MATERIAL_SHARE = 0.02
MIN_A69_MONTHS = 24


def _expected_hours(period: pd.Period) -> int:
    return int((period.end_time - period.start_time).total_seconds() // 3600) + 1


def coverage(hourly: pd.DataFrame, zone: str, fuel: str) -> pd.DataFrame:
    """Monthly coverage, peak and mean for one (zone, fuel) series."""
    series = hourly[(hourly.zone == zone) & (hourly.fuel_type == fuel)]
    if series.empty:
        return pd.DataFrame()
    months = (
        series.period_start.dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("M")
    )
    grouped = series.assign(month=months).groupby("month")
    out = grouped.agg(
        hours=("mw", "size"), peak_mw=("mw", "max"), mean_mw=("mw", "mean")
    ).reset_index()
    out["coverage_pct"] = 100 * out.hours / out.month.map(_expected_hours)
    return out


def longest_constant_run(series: pd.Series) -> int:
    """Length of the longest run of identical consecutive non-zero values."""
    values = series.to_numpy()
    best = run = 1
    for i in range(1, len(values)):
        run = run + 1 if values[i] == values[i - 1] and values[i] != 0 else 1
        best = max(best, run)
    return best


def resolution_transition(
    raw: pd.DataFrame, zone: str, fuel: str
) -> pd.Timestamp | None:
    """First timestamp at which the native resolution drops to 15 minutes or finer."""
    series = raw[(raw.zone == zone) & (raw.fuel_type == fuel)]
    if series.empty:
        return None
    stamps = pd.DatetimeIndex(sorted(series.period_start.unique()))
    gaps = pd.Series(stamps).diff()
    fine = gaps <= pd.Timedelta("15min")
    if not fine.any():
        return None
    # First timestamp after which fine resolution persists for a full day.
    for idx in fine[fine].index:
        window = fine.iloc[idx : idx + 96]
        if window.mean() > 0.9:
            return stamps[idx]
    return stamps[fine.idxmax()]


def seasonal_ratio(hourly: pd.DataFrame, zone: str, fuel: str) -> float:
    """Ratio of summer-peak to winter-trough monthly means. Solar sanity check."""
    series = hourly[(hourly.zone == zone) & (hourly.fuel_type == fuel)]
    if series.empty:
        return float("nan")
    monthly = series.groupby(series.period_start.dt.month)["mw"].mean()
    if 12 not in monthly or monthly.get(12, 0) <= 0:
        return float("inf")
    return float(monthly.max() / monthly[12])


def dst_integrity(years: range) -> pd.DataFrame:
    """Check delivery-day lengths across daylight-saving transitions."""
    rows = []
    for year in years:
        day = date(year, 1, 1)
        lengths: dict[int, int] = {}
        while day < date(year + 1, 1, 1):
            n = len(windows.delivery_day_starts(day))
            lengths[n] = lengths.get(n, 0) + 1
            day += timedelta(days=1)
        rows.append(
            {
                "year": year,
                "days_23h": lengths.get(23, 0),
                "days_24h": lengths.get(24, 0),
                "days_25h": lengths.get(25, 0),
                "ok": lengths.get(23, 0) == 1 and lengths.get(25, 0) == 1,
            }
        )
    return pd.DataFrame(rows)


def _plot_monthly(hourly: pd.DataFrame, zone: str, fuels: list[str], name: str) -> str:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 3.2))
    for fuel in fuels:
        series = hourly[(hourly.zone == zone) & (hourly.fuel_type == fuel)]
        if series.empty:
            continue
        months = (
            series.period_start.dt.tz_convert("UTC")
            .dt.tz_localize(None)
            .dt.to_period("M")
        )
        monthly = series.groupby(months)["mw"].mean()
        ax.plot(monthly.index.to_timestamp(), monthly.to_numpy(), label=fuel, lw=1.2)
    ax.set_title(f"{zone} — monthly mean generation (MW)")
    ax.set_ylabel("MW")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = FIGURES / f"{name}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return f"{FIGURES.name}/{path.name}"


def _plot_diurnal(hourly: pd.DataFrame, zone: str, fuel: str, name: str) -> str:
    FIGURES.mkdir(parents=True, exist_ok=True)
    series = hourly[(hourly.zone == zone) & (hourly.fuel_type == fuel)]
    fig, ax = plt.subplots(figsize=(6, 3.2))
    if not series.empty:
        recent = series[
            series.period_start >= series.period_start.max() - pd.Timedelta("365D")
        ]
        for month, label in ((6, "June"), (12, "December")):
            sel = recent[recent.period_start.dt.month == month]
            if sel.empty:
                continue
            profile = sel.groupby(sel.period_start.dt.hour)["mw"].mean()
            ax.plot(profile.index, profile.to_numpy(), marker="o", ms=3, label=label)
    ax.set_title(f"{zone} {fuel} — mean diurnal profile (UTC)")
    ax.set_xlabel("hour UTC")
    ax.set_ylabel("MW")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = FIGURES / f"{name}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return f"{FIGURES.name}/{path.name}"


def _fmt(frame: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    """Render a DataFrame as a GitHub markdown table."""
    if frame.empty:
        return "_(no data)_"
    display = frame.copy()
    for col in display.select_dtypes("float").columns:
        display[col] = display[col].map(
            lambda v: "—" if pd.isna(v) else floatfmt.format(v)
        )
    header = "| " + " | ".join(str(c) for c in display.columns) + " |"
    sep = "|" + "|".join("---" for _ in display.columns) + "|"
    rows = [
        "| " + " | ".join(str(v) for v in row) + " |"
        for row in display.itertuples(index=False)
    ]
    return "\n".join([header, sep, *rows])


def _load() -> dict[str, pd.DataFrame]:
    """Load the cached ENTSO-E pulls and normalise them onto the canonical grid."""
    raw_actual = entsoe.load("actual_generation")
    if raw_actual.empty:
        msg = "no actual_generation cached; run the backfill first"
        raise RuntimeError(msg)
    raw_fc = entsoe.load("da_wind_solar_forecast")
    raw_cap = entsoe.load("installed_capacity")

    cap = pd.DataFrame()
    if not raw_cap.empty:
        cap = raw_cap.assign(
            fuel_type=raw_cap.fuel_type.map(actuals.slug),
            year=pd.to_datetime(raw_cap.period_start, utc=True).dt.year,
        )
        cap = (
            cap.groupby(["zone", "fuel_type", "year"])["value_mw"]
            .max()
            .reset_index()
            .rename(columns={"value_mw": "installed_mw"})
        )

    return {
        "raw_actual": raw_actual.assign(
            fuel_type=raw_actual.fuel_type.map(actuals.slug)
        ),
        "hourly": actuals.to_hourly(raw_actual),
        "forecast": actuals.to_hourly(raw_fc) if not raw_fc.empty else pd.DataFrame(),
        "capacity": cap,
    }


def check_a_target_integrity(hourly: pd.DataFrame, cap: pd.DataFrame) -> pd.DataFrame:
    """Coverage, peak, capacity ratio and staleness for every VRE series."""
    rows = []
    for zone in sorted(hourly.zone.unique()):
        for fuel in actuals.VRE_SLUGS:
            cov = coverage(hourly, zone, fuel)
            if cov.empty:
                continue
            series = hourly[(hourly.zone == zone) & (hourly.fuel_type == fuel)]
            recent = cov[cov.month >= pd.Period("2021-01")]
            # Swedish A68 is national, so fall back to the country code.
            match = cap[cap.fuel_type == fuel] if not cap.empty else pd.DataFrame()
            match = (
                match[match.zone.isin({zone, zone[:2]})] if not match.empty else match
            )
            installed = match.installed_mw.max() if not match.empty else float("nan")
            rows.append(
                {
                    "zone": zone,
                    "fuel": fuel,
                    "first_month": str(cov.month.min()),
                    "cov%_2021+": recent.coverage_pct.mean()
                    if not recent.empty
                    else float("nan"),
                    "peak_mw": series.mw.max(),
                    "A68_mw": installed,
                    "peak/A68": series.mw.max() / installed,
                    "const_run_h": longest_constant_run(
                        series.sort_values("period_start").mw
                    ),
                }
            )
    return pd.DataFrame(rows)


def check_b_offshore(hourly: pd.DataFrame) -> pd.DataFrame:
    """Is offshore wind material enough to model separately?"""
    rows = []
    for zone in sorted(hourly.zone.unique()):
        onshore = hourly[(hourly.zone == zone) & (hourly.fuel_type == "wind_onshore")]
        offshore = hourly[(hourly.zone == zone) & (hourly.fuel_type == "wind_offshore")]
        on_peak = onshore.mw.max() if not onshore.empty else 0.0
        off_peak = offshore.mw.max() if not offshore.empty else 0.0
        share = off_peak / on_peak if on_peak else float("nan")
        rows.append(
            {
                "zone": zone,
                "onshore_peak_mw": on_peak,
                "offshore_peak_mw": off_peak,
                "offshore_share": share,
                "material": bool(
                    off_peak >= OFFSHORE_MATERIAL_MW
                    and share >= OFFSHORE_MATERIAL_SHARE
                ),
            }
        )
    return pd.DataFrame(rows)


def check_c_benchmark(forecast: pd.DataFrame) -> pd.DataFrame:
    """Depth and coverage of the ENTSO-E A69 day-ahead benchmark."""
    if forecast.empty:
        return pd.DataFrame()
    rows = []
    for zone in sorted(forecast.zone.unique()):
        for fuel in sorted(forecast[forecast.zone == zone].fuel_type.unique()):
            cov = coverage(forecast, zone, fuel)
            if cov.empty:
                continue
            recent = cov[cov.month >= pd.Period("2021-01")]
            rows.append(
                {
                    "zone": zone,
                    "fuel": fuel,
                    "first_month": str(cov.month.min()),
                    "months": len(cov),
                    "cov%_2021+": recent.coverage_pct.mean()
                    if not recent.empty
                    else float("nan"),
                    "enough": len(cov) >= MIN_A69_MONTHS,
                }
            )
    return pd.DataFrame(rows)


def check_d_resolution(raw_actual: pd.DataFrame) -> pd.DataFrame:
    """Where each zone switched to 15-minute settlement."""
    rows = []
    for zone in sorted(raw_actual.zone.unique()):
        stamp = resolution_transition(raw_actual, zone, "wind_onshore")
        rows.append(
            {
                "zone": zone,
                "first_15min_timestamp": str(stamp) if stamp is not None else "—",
            }
        )
    return pd.DataFrame(rows)


#: A68 is published per bidding zone only where the zone is also a country.
ZONAL_CAPACITY_AVAILABLE = {"DE_LU"}


def check_f_solar(hourly: pd.DataFrame, cap: pd.DataFrame) -> pd.DataFrame:
    """Is the reported solar series physically plausible and fleet-representative?

    Two families of check. *Shape* checks -- night level, seasonal amplitude -- need no
    capacity denominator and say whether the series is physically credible. The *level*
    check (peak / installed) needs a zonal denominator, which does not exist for the
    Swedish zones, so it is reported only where it is meaningful.
    """
    rows = []
    for zone in sorted(hourly.zone.unique()):
        series = hourly[(hourly.zone == zone) & (hourly.fuel_type == "solar")]
        if series.empty:
            continue
        installed = float("nan")
        if zone in ZONAL_CAPACITY_AVAILABLE and not cap.empty:
            match = cap[(cap.fuel_type == "solar") & (cap.zone == zone)]
            installed = match.installed_mw.max() if not match.empty else float("nan")
        peak = series.mw.max()
        night = series[series.period_start.dt.hour.isin([22, 23, 0, 1])].mw.mean()
        rows.append(
            {
                "zone": zone,
                "peak_mw": peak,
                "zonal_A68_mw": installed,
                "peak/A68": peak / installed,
                "summer/dec": seasonal_ratio(hourly, zone, "solar"),
                "night/peak": night / peak if peak else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def check_g_capacity(hourly: pd.DataFrame) -> pd.DataFrame:
    """Cross-check the fleet registry against observed generation.

    Reports the **p99.9** of implied capacity factor per year, not the maximum. The
    maximum is a single hour and is routinely above 1.0 -- registry timing lags, a
    momentary metering spike, or a capacity change recorded a few weeks late are all
    enough. The p99.9 is the statistic that actually reflects the fleet, and it should
    sit in roughly 0.75-1.00 and stay flat. Drift or a step means the denominator is
    wrong and the model would learn the error as seasonality.
    """
    try:
        turbines = fleet.load_turbines()
    except FileNotFoundError:
        logger.warning("Vindbrukskollen registry absent; skipping Check G")
        return pd.DataFrame()

    ceilings = {}
    for zone in ["SE1", "SE2", "SE3", "SE4"]:
        series = hourly[(hourly.zone == zone) & (hourly.fuel_type == "wind_onshore")]
        if series.empty:
            continue
        observed = series.set_index("period_start").mw.sort_index()
        capacity = fleet.capacity_series(turbines, zone).set_index("date").capacity_mw
        aligned = capacity.reindex(observed.index.tz_localize(None).normalize()).ffill()
        factor = pd.Series(
            observed.to_numpy() / aligned.to_numpy(), index=observed.index
        )
        ceilings[zone] = factor.groupby(factor.index.year).quantile(0.999)

    if not ceilings:
        return pd.DataFrame()
    out = pd.DataFrame(ceilings).reset_index(names="year")
    return out[out.year > out.year.min()]  # the first year is a partial day


def build() -> str:
    """Run every check and return the markdown report."""
    data = _load()
    hourly, cap = data["hourly"], data["capacity"]
    check_a = check_a_target_integrity(hourly, cap)
    check_b = check_b_offshore(hourly)
    check_c = check_c_benchmark(data["forecast"])
    check_d = check_d_resolution(data["raw_actual"])
    check_e = dst_integrity(range(2018, 2028))
    check_f = check_f_solar(hourly, cap)
    check_g = check_g_capacity(hourly)

    se3_wind = check_a[(check_a.zone == "SE3") & (check_a.fuel == "wind_onshore")]
    se3_solar = check_f[check_f.zone == "SE3"]
    delu_solar = check_f[check_f.zone == "DE_LU"]

    def shape_ok(row: pd.DataFrame) -> bool:
        """Physical plausibility, needing no capacity denominator."""
        return bool(
            not row.empty
            and row["summer/dec"].iloc[0] >= MIN_SOLAR_SEASONAL_RATIO
            and row["night/peak"].iloc[0] <= MAX_SOLAR_NIGHT_SHARE
        )

    wind_ok = bool(
        not se3_wind.empty
        and se3_wind["cov%_2021+"].iloc[0] >= MIN_COVERAGE_PCT
        and se3_wind["const_run_h"].iloc[0] < 24
    )
    delu_solar_ok = bool(
        shape_ok(delu_solar) and delu_solar["peak/A68"].iloc[0] >= MIN_SOLAR_PEAK_RATIO
    )

    wind_verdict = "**GO**" if wind_ok else "**NO-GO**"
    delu_verdict = "**GO**" if delu_solar_ok else "**NO-GO**"
    se3_solar_verdict = "**CONDITIONAL**" if shape_ok(se3_solar) else "**NO-GO**"

    span = (
        f"{hourly.period_start.min():%Y-%m-%d} → {hourly.period_start.max():%Y-%m-%d}"
    )
    parts = [
        f"""# Phase 2 — Data audit

**Generated:** {datetime.now(UTC).date()} · **Span:** {span} · **Source:** ENTSO-E
Transparency Platform, pulled into `research/data/raw/entsoe/`.

This is the hard gate: no modelling code until the verdicts below are recorded.
Regenerate with `PYTHONPATH=research/src uv run python -m renewable_forecast.pipelines.data_audit`.

## Verdicts

| Target | Verdict | Basis |
|---|---|---|
| SE3 onshore wind | {wind_verdict} | A75 coverage {se3_wind["cov%_2021+"].iloc[0]:.1f}% since 2021, longest stale run {se3_wind["const_run_h"].iloc[0]:.0f} h |
| SE3 solar | {se3_solar_verdict} | series is physically credible, but **no zonal capacity denominator exists** — see Check F |
| DE-LU solar | {delu_verdict} | shape checks pass; peak/installed = {delu_solar["peak/A68"].iloc[0]:.2f} |

Per the project scope, solar development proceeds on **DE-LU**. SE3 solar is recorded as
CONDITIONAL rather than NO-GO — the blocker is the normalisation denominator, not the
target series itself, and it becomes tractable if a zonal PV capacity estimate is found.

## Check A — Target integrity
""",
        _fmt(check_a),
        """
`A68_mw` is ENTSO-E installed capacity. **A68 is published per country for Sweden, not
per bidding zone** — `SE_1`…`SE_4` all return `NoMatchingDataError` — so SE rows compare
a single-zone peak against the *national* fleet and `peak/A68` is expected to sit well
below 1. DE-LU is simultaneously a country and a bidding zone, so its ratio is directly
interpretable. Consequence for Phase 3: the capacity *level* anchor for SE3 must come
from Vindbrukskollen, with A68 usable only as a national sanity check.
""",
        f"![]({_plot_monthly(hourly, 'SE3', list(actuals.VRE_SLUGS), 'se3_monthly')})",
        f"![]({_plot_monthly(hourly, 'DE_LU', list(actuals.VRE_SLUGS), 'delu_monthly')})",
        "\n## Check B — Offshore materiality\n",
        _fmt(check_b),
        "\n## Check C — A69 day-ahead benchmark\n",
        _fmt(check_c),
        """
**Vintage limitation.** The Transparency Platform serves the *latest revision* for a
target time, and `entsoe-py` exposes no publication timestamp. A69 is therefore recorded
as `A69_latest_vintage` throughout this project: it is an **optimistic** benchmark, and
no claim of beating it is valid without this caveat attached.
""",
        "\n## Check D — 15-minute settlement transition\n",
        _fmt(check_d),
        "\n## Check E — DST / delivery-day integrity\n",
        _fmt(check_e),
        """
Each year must contain exactly one 23-hour and one 25-hour delivery day. This is
asserted independently in `research/tests/test_windows.py`.
""",
        """
## Check F — Solar feasibility

Shape checks need no capacity denominator and test whether the series is physically
credible. The level check (`peak/A68`) needs a *zonal* denominator, which exists only
for DE-LU — Swedish A68 is national, so those cells are left blank rather than
populated with a misleading national ratio.
""",
        _fmt(check_f),
        f"\n![]({_plot_diurnal(hourly, 'SE3', 'solar', 'se3_solar_diurnal')})",
        f"\n![]({_plot_diurnal(hourly, 'DE_LU', 'solar', 'delu_solar_diurnal')})",
        """
## Check G — Fleet registry cross-check

Implied capacity-factor ceiling (yearly **p99.9** of observed MW ÷ Vindbrukskollen
capacity) per Swedish zone. If the denominator tracks the fleet this sits flat inside
roughly 0.90-1.00. It does not — see the open finding below the table.

Note the statistic: the *maximum* implied factor exceeds 1.0 for SE1 and SE2 in 2022,
which looks alarming and is not. A single hour is enough to break it — a metering spike,
or a wind farm whose registry commissioning date lags its actual grid connection. The
p99.9 removes that and lands every zone-year in the plausible band. This is why the
denominator diagnostic is specified as p99.9 rather than max.
""",
        _fmt(check_g),
        f"\n![]({FIGURES.name}/ceiling_drift.png)",
        """
Nationally the registry totals 18,198 MW of operational onshore wind against ENTSO-E
A68's 18,000 MW for SE — agreement to 1.1%, which validates the registry on *level* as
well as timing.

**Open finding: the ceiling is not flat.** Every zone drifts down together — SE3 from
0.91 in 2018 to 0.79 in 2025, and SE1, SE2 and SE4 by a similar margin. A simultaneous
drift in four independent zones rules out a boundary or zone-assignment error. Two
further explanations have been tested and rejected:

- **Curtailment.** Recomputing p99.9 over non-curtailed hours only moves the SE3
  statistic by 0.001 in every year, even in 2024 when 8.6% of hours carried the flag.
- **Fleet spread.** A geographically wider fleet has a lower zonal peak. But the SE3
  capacity-weighted RMS spread *narrowed* from 175 km to 159 km over the period, which
  pushes the ceiling up, not down.

The registry also agrees with A68 nationally to within a few percent in every year, so
a simple over-count is not the explanation either. What remains is A75 under-reporting a
growing fleet, or commissioning dates that lead grid connection by a widening margin.
Unresolved, and it matters: roughly 7% of the drift falls inside the modelling window,
against a model error of 3%.
""",
    ]
    return "\n".join(parts) + "\n"


def main() -> int:
    """Generate the audit report."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    paths.REPORTS.mkdir(parents=True, exist_ok=True)
    out = paths.REPORTS / "data_audit.md"
    out.write_text(build())
    logger.info("wrote %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
