# Integration contract — `renewable-forecast` → `grid-signals`

**Status: specification only. No code in `grid-signals` implements this yet, and none
should until the Phase 7 dry-run exit criterion is met.**

This document exists so that when integration happens it is a mechanical exercise rather
than a negotiation. It describes what this project would publish, what it needs in
return, and what must be true before either side writes code.

## Precondition

Integration does not begin until the operational dry-run has produced **~30 consecutive
scheduled runs with near-total success, and live nMAE within ~1.25× of backtest nMAE at
matched lead hours**. A wider gap means train/serve skew and must be diagnosed first —
that check is the entire point of the dry-run, and shipping past it would move an unknown
error into a system that other things depend on.

## Table

`renewable_forecasts`, primary key `(zone, issue_time, target_period_start, fuel_type, quantile)`.

| column | type | notes |
|---|---|---|
| `zone` | VARCHAR | matches `grid_signals.models.zones.BiddingZone` |
| `fuel_type` | VARCHAR | existing slugs: `wind_onshore`, `wind_offshore`, `solar` |
| `issue_time` | TIMESTAMPTZ | 09:00 UTC on the issue day |
| `target_period_start` | TIMESTAMPTZ | follows the existing `period_start` convention |
| `target_period_end` | TIMESTAMPTZ | follows the existing `period_end` convention |
| `quantile` | DOUBLE PRECISION | 0.05…0.95 by 0.05, plus 0.01/0.99. `NULL` is the deterministic forecast |
| `capacity_factor` | DOUBLE PRECISION | the model's native output |
| `generation_mw` | DOUBLE PRECISION | `capacity_factor × capacity_mw_assumed` |
| `capacity_mw_assumed` | DOUBLE PRECISION | the denominator used, so CF stays interpretable later |
| `model_version` | VARCHAR | git SHA + config fingerprint, always resolvable |
| `created_at` | TIMESTAMPTZ | |

Naming deliberately mirrors `src/grid_signals/db/schema.py`. All times are tz-aware UTC.

`capacity_mw_assumed` is not redundant. The denominator is a modelling assumption that
changes as the fleet grows, and without it a capacity factor stored today cannot be
reinterpreted tomorrow.

## Guarantees out

- One complete forecast set per delivery day, published by **09:30 UTC**.
- Idempotent upsert, matching the existing `ON CONFLICT … DO UPDATE` pattern in
  `db/queries.py`.
- Forecasts are **immutable per `issue_time`**. A revision gets a new `issue_time`; it
  never overwrites an existing one. This is what makes honest backtesting possible later
  — it is precisely the property ENTSO-E's A69 lacks, which is why A69 is unusable as a
  day-ahead benchmark.
- `model_version` always resolves to a commit.

## Guarantees in

- `generation_by_type` for the target zone at ≤26 h latency. The existing health check in
  `health.py` already enforces this.
- A stable capacity source — either an `installed_capacity` table or an agreed static
  file. Note that **ENTSO-E A68 is published per country for Sweden**, so a zonal
  denominator cannot come from it; this project derives SE3 capacity from Vindbrukskollen
  anchored nationally to A68.
- Stable fuel slugs.

## Failure mode

If no forecast is published by 10:00 UTC, consumers fall back to ENTSO-E A69 and the
health check alerts. A69 is unsuitable as a *benchmark* but perfectly serviceable as a
fallback *input* — those are different uses.

## Consumption surface (sketch only, not built)

An agent tool mirroring the signatures in `src/grid_signals/agent/tools.py`:

```
get_renewable_forecast(zone, date, fuel_type, quantiles=None)
  → per-hour capacity factor and MW at the requested quantiles,
    with model_version and capacity_mw_assumed attached
```

And a dashboard fan chart alongside the existing `wind_vs_price` panel in
`app/charts.py`.

## Why this matters to the roadmap

`ROADMAP.md` Direction H proposes a price model. Renewable generation is the dominant
driver of Nordic-Baltic day-ahead prices, so these quantiles are the highest-value input
it could take — and because they are a *distribution* rather than a point, the price
model can propagate uncertainty instead of inventing it.

## Caveats that must travel with the data

Any consumer, human or model, needs to know:

1. **The 184-day holdout is the only honest accuracy figure.** Development-set numbers
   are for model selection, not for setting expectations.
2. **The quantile model is mildly underdispersed** (0.737 coverage at nominal 0.80 on the
   development set). Intervals are somewhat too narrow; treat them as a lower bound on
   uncertainty until this is closed.
3. **Winter forecasts over-predict** (DJF nBIAS −0.0138), consistent with unmodelled
   icing losses.
4. **Features are at least as stale as the real forecast would be** — the per-hour offset
   selection is conservative by construction, so reported skill is a floor.
