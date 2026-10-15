# Phase 3 — Evaluation protocol

**Frozen:** 2026-09-20. Changing anything in this document invalidates every result
scored against it. The point of freezing the protocol *before* any model exists is that
a model cannot then be evaluated against a bar that moved to accommodate it.

## Task

| Parameter | Value | Why |
|---|---|---|
| Zone / target | SE3, `wind_onshore` capacity factor | Phase 2 GO verdict |
| Issue time | 09:00 UTC on day D | gate closure is 11:00 UTC under CET but **10:00 UTC under CEST**; 09:00 keeps ≥1 h slack year-round |
| NWP run | 00z of day D, named explicitly | "latest available" is how train/serve skew creeps in |
| Delivery window | 00:00–24:00 local on D+1 | 23, 24 or 25 hourly targets depending on DST |
| Lead times | interval starts +22…+46 h; window ends +47 h | verified by `test_lead_hours_stay_within_the_frozen_window` |
| Output | 19 quantiles (0.05…0.95), in CF and MW | |

## Splits

Rolling-origin expanding window, monthly origins, **7-day embargo** between train end and
test start. **The unit of resampling is the delivery day, never the hour** — adjacent
hours within a day correlate at ~0.95, so treating hours as independent inflates the
effective sample size roughly 24-fold and makes every confidence interval a fiction.

- Development: **2018-01-01 → 2026-03-19** (3000 delivery days, 85 folds)
- Holdout: **2026-03-20 → 2026-09-19** (184 days) — **SEALED**, opened exactly once for
  the headline table at the end of Phase 5.

> **Amendment, 2026-09-21 — realised window.** The split *rule* above is unchanged and
> still binding. The *realised* development window is shorter, because Phase 4
> established that the matched-lead NWP archive only begins 2024-03-06
> (`openmeteo_vintage.md`). Every model in `modelling.md` is therefore scored over
> **2024-02-16 → 2026-03-19, 763 days, 18 folds** — not the 3000 days assumed when this
> document was frozen. The baseline table immediately below predates the NWP features
> and was scored over the full target history, which is why its numbers differ from the
> leaderboard in `modelling.md`. The two are not comparable; `modelling.md` is the
> operative board.

## Metrics

Point metrics are normalised by **installed capacity, not mean generation**. Mean-
normalising makes numbers incomparable across years as the fleet grows: the same physical
error shrinks on paper simply because the denominator grew.

nMAE · nRMSE · nBIAS · **CRPS** (headline) · pinball per level · coverage and reliability
· **PIT histogram** (how underdispersion gets caught) · sharpness · interval score.
Reported pooled and broken down by lead hour and by season — drivers like icing are
seasonal by nature, so a pooled number hides where the model actually fails.

Significance uses a **day-block bootstrap** on the metric *difference*. With ~180 test
days, differences under roughly 3% relative will not be significant.

## Baseline results (development set, 85 folds)

| forecaster | nMAE | nRMSE | nBIAS | CRPS | cov@80 | cov@90 | sharp@80 | CRPSS vs clim. |
|---|---|---|---|---|---|---|---|---|
| A69_latest_vintage | 0.0177 | 0.0287 | −0.0015 | 0.0142 | 0.793 | 0.902 | 0.054 | **+0.878** |
| climatology | 0.1598 | 0.2022 | 0.0311 | 0.1161 | 0.775 | 0.876 | 0.503 | 0.000 |
| persistence | 0.1952 | 0.2509 | 0.0029 | 0.1417 | 0.813 | 0.911 | 0.552 | −0.221 |

Persistence being *worse* than climatology is expected: at a 48-hour lag, yesterday's
wind carries less information than the seasonal-diurnal climatology does.

## The A69 benchmark is not a day-ahead benchmark

A69 scores **nMAE = 1.77% of installed capacity**. Published day-ahead wind forecast skill
for a bidding zone is typically 3–6% of capacity, so this is three to four times better
than the state of the art. That is not credible for a forecast made before gate closure.

Diagnostics on the 76,101 overlapping hours:

- correlation with actuals **0.988**
- nMAE stable at 1.2–2.3% of capacity in every year since 2018
- error autocorrelation **0.93 at lag 1**, 0.31 at lag 24
- exact matches with actuals: **0.1%**

So it is a genuine forecast, not a relabelled measurement — but an implausibly good one.
The Transparency Platform serves the *latest revision* for a target time and `entsoe-py`
exposes no publication timestamp, so the values almost certainly incorporate information
that did not exist at 09:00 UTC the day before.

**Consequences, binding on everything downstream:**

1. A69 is named `A69_latest_vintage` in all code and reports. It is an **upper reference**,
   closer to a short-horizon forecast than a day-ahead one — not a bar to clear.
2. The operative bars for Phase 5 are **climatology** (the CRPS denominator), **persistence**,
   and the **physical power-curve baseline** added in Phase 4.
3. No claim of "beating the TSO" may be made from this data. Obtaining a true day-ahead
   benchmark requires capturing A69 at issue time, one request per day — recommended as a
   standing job, not started here, since ongoing self-archiving was deliberately deferred.

## Amendment, 2026-10-15 — quarter-hour wind and DE-LU solar

This adds a separate product evaluation; it does not replace the frozen hourly board
or open the 2026-03-20 → 2026-09-19 holdout. The split dates are now explicit in
`configs/base.yaml`, so refreshing inputs cannot move the sealed window.

- **Evaluation:** December 2025, January 2026 and February 2026, three monthly
  rolling-origin folds, each with a seven-day embargo. Only complete delivery days
  with genuine quarter-hour actuals and required weather are scored. Each arm sees
  the same intervals. Days outside this set can enter production fitting only.
- **Wind Stage 1:** fit the existing quantile model on hourly mean MW. Interpolate
  weather linearly, within each model/run/point/height, before applying the power
  curve. Compare against the same hourly model's quantiles repeated over its four
  quarter-hours. No claim of native sub-hourly weather skill is made. Hourly actuals
  are arithmetic averages of four complete quarter-hours; they are never expanded
  into artificial quarter-hour training labels.
- **Information-age correction:** both wind arms date the entire whole-day NWP block
  to the latest forward trajectory input (+3 h, rounded to the following hour for
  interpolation). The earlier hourly guard dated these features only to the target
  instant and could admit too-fresh weather at an offset boundary. The September
  hourly tables are retained as historical results, not corrected-code accuracy.
- **Solar:** DE-LU A75 estimated generation, native 15-minute intervals. Normalize
  by the latest cached annual A68 capacity snapshot preceding each issue. Annual
  chunk-boundary carryovers resolve to the larger snapshot for this growing fleet.
  No interpolation to a future annual capacity is allowed. This is a provisional
  denominator until dated MaStR capacity is available; A68 publication vintages are
  not recoverable, so the normalization is not claimed to be vintage-audited.
- **Solar evaluation hours:** headline marginal metrics use intervals whose midpoint
  solar elevation exceeds **5° at at least one declared site**. Fit on daylight
  (>0°); set all quantiles to zero when every site is below the horizon. Report
  daylight and all-hours diagnostics separately, so night cannot inflate headline
  skill. Interval means are approximated by midpoint PV output.
- **Solar references:** clear-sky-index climatology, 48-hour smart persistence and a
  physical PV baseline with one derating factor fitted inside each training fold.
  Irradiance uses a pinned `ecmwf_ifs025` Previous Runs archive at safe whole-day
  offsets, with clear-sky-index interpolation. The following hourly interpolation
  endpoint must also predate issue; missing endpoint values and hours remain missing.
  The first fleet is an explicit equal-area six-site approximation, with half its
  panels south-facing and a quarter each east/west. It is not a MaStR fleet model.
- **Metrics:** the existing marginal metrics, plus median quarter-hour ramp MAE and
  error in the timing of the largest absolute daily ramp. Paired CRPS differences
  use the same day-block bootstrap. All-hours hourly-averaged **point** MAE is a
  diagnostic only; averaging marginal quantiles is not a joint distribution.
- **Exclusions:** incomplete intervals, missing weather and CF outside [0,1] for
  solar. Record actual scored day/interval counts. These product tests do not score
  scenarios; energy/variogram scoring remains a prerequisite for using joint paths.

Operational forecasts can fit on observations from days ending before the issue day,
including past holdout days, without scoring them. The production path and the
development scorer use separate cutoffs. Forecast files identify zone, fuel,
resolution, interval end, issue time, capacity assumption and model version.

## Original Phase 4 follow-up

The **physical power-curve baseline** — capacity-weighted NWP wind speed → density
correction → fleet power curve → CF, with no learning — lands in Phase 4 once NWP features
exist. It is the baseline that says whether machine learning adds anything over physics,
and Phase 5 does not start without it.

## Reproducing

```bash
PYTHONPATH=research/src uv run python -m renewable_forecast.pipelines.train
PYTHONPATH=research/src uv run python -c "
from renewable_forecast import experiment; print(experiment.leaderboard())"
```
