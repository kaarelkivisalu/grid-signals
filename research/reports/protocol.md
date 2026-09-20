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

## Still to be added

The **physical power-curve baseline** — capacity-weighted NWP wind speed → density
correction → fleet power curve → CF, with no learning — lands in Phase 4 once NWP features
exist. It is the baseline that says whether machine learning adds anything over physics,
and Phase 5 does not start without it.

## Reproducing

```bash
PYTHONPATH=research/src uv run python -m renewable_forecast.pipelines.backtest
PYTHONPATH=research/src uv run python -c "
from renewable_forecast import experiment; print(experiment.leaderboard())"
```
