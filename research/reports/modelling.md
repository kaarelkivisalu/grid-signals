# Phase 5 — Modelling

**Run:** 2026-09-20, development set only. The 184-day holdout
(2026-03-20 → 2026-09-19) remains **sealed** and is not reported here.

Scored on the frozen protocol (`reports/protocol.md`): 18 rolling-origin folds over 763
development days, 7-day embargo, resampling by delivery day. Metrics normalised by
installed capacity.

## Leaderboard

| forecaster | nMAE | nRMSE | nBIAS | CRPS | cov@80 | cov@90 | sharp@80 | CRPSS vs clim. | significant |
|---|---|---|---|---|---|---|---|---|---|
| *A69_latest_vintage* | *0.0147* | *0.0242* | *0.0000* | *0.0118* | 0.769 | 0.878 | 0.041 | *+0.900* | — |
| **lightgbm_quantile** | **0.0307** | 0.0418 | −0.0026 | **0.0232** | 0.737 | 0.852 | 0.090 | **+0.804** | yes |
| lightgbm_point_monotone | 0.0312 | 0.0421 | −0.0019 | 0.0241 | 0.765 | 0.879 | 0.093 | +0.796 | yes |
| physical_power_curve | 0.0357 | 0.0481 | 0.0039 | 0.0272 | 0.778 | 0.885 | 0.107 | +0.770 | yes |
| ridge_sanity_floor | 0.0361 | 0.0475 | −0.0039 | 0.0273 | 0.768 | 0.887 | 0.104 | +0.769 | yes |
| climatology | 0.1632 | 0.2081 | 0.0579 | 0.1182 | 0.743 | 0.842 | 0.455 | 0.000 | — |
| persistence | 0.1960 | 0.2500 | 0.0010 | 0.1428 | 0.784 | 0.892 | 0.521 | −0.208 | yes |

A69 is italicised because it is **not a bar**: it scores better than published day-ahead
wind skill by a factor of three, so the revision served by the Transparency Platform
postdates gate closure. See `reports/protocol.md`.

Significance is a day-block bootstrap on the CRPS *difference* against climatology, 2000
draws. Persistence is significantly **worse** than climatology, which is the expected
result at a 48-hour lag.

## What the numbers say

**The sanity floor passes decisively.** Ridge on eight physical features beats
climatology by 76.9% on CRPS. The pipeline is sound; nothing downstream is chasing a bug.

**Machine learning beats physics, modestly.** The best model improves on the physical
power-curve baseline by **15% on CRPS** (0.0232 vs 0.0272) and **14% on nMAE** (0.0307 vs
0.0357). Real and significant, but the honest shape of this problem is a physics problem
with a statistical correction on top — not one that machine learning solves on its own.
The feature importances say the same thing: the power-curve transform and its one-hour
lag carry 38% of total gain between them.

| feature | share of gain |
|---|---|
| power_curve_model_mean | 19.0% |
| power_curve_model_mean_shift−1 | 18.9% |
| power_curve_model_mean_shift+1 / −3 | 7.2% |
| wind_speed_100m_model_mean (+ shifts) | 9.8% |
| day-of-year terms | 4.6% |

**Error grows with lead time, as it must.**

| lead block | nMAE |
|---|---|
| +22…+29 h | 0.0263 |
| +30…+37 h | 0.0304 |
| +38…+46 h | 0.0348 |

**Winter is the hard season, and the bias says why.**

| season | nMAE | nBIAS |
|---|---|---|
| DJF | 0.0356 | **−0.0138** |
| MAM | 0.0290 | −0.0042 |
| JJA | 0.0255 | +0.0003 |
| SON | 0.0293 | +0.0077 |

`nBIAS = mean(actual − predicted)`, so the winter figure means the model **over-predicts
in DJF** — the forecast says windy and the fleet delivers less. That is the signature of
icing: the NWP is right about the wind and wrong about what the turbines do with it. The
icing proxies in the feature set clearly do not capture it fully, which moves an explicit
icing model up the roadmap from "nice to have" to "the largest identified residual".

## The calibration defect, and its fix

The first leaderboard was uncalibrated, and the coverage column diagnosed itself:

| forecaster | cov@80 before | after |
|---|---|---|
| lightgbm_point_monotone | **0.327** | 0.765 |
| lightgbm_quantile | 0.612 | 0.737 |
| ridge_sanity_floor | 0.762 | 0.768 |
| physical_power_curve | 0.784 | 0.778 |

The ordering was the diagnosis: the tighter a model fitted its training data, the worse
its intervals. Every dressed forecaster was estimating its residual distribution on the
rows it had just been fitted to, and in-sample residuals for a boosted tree are tiny and
meaningless out of sample. The physical baseline looked fine only because an affine
correction cannot overfit.

Each training window now reserves its most recent quarter — split by whole delivery days
— for estimating spread, and the quantile model is conformalised on those held-out days.
The point model's CRPS *improved* as a result (0.0267 → 0.0241): honest intervals score
better, not worse.

**Residual gap.** `lightgbm_quantile` is still underdispersed at 0.737 against a nominal
0.80. The conformal layer closed most of the gap (0.612 → 0.737) but not all of it. The
likely cause is that a 25% calibration slice of a rolling window is small and its most
recent days are not exchangeable with the test month. Worth trying before Phase 6: a
larger calibration fraction, the adaptive-conformal online update that
`models/conformal.py` already provides but the pipeline does not yet drive, and
stratifying by season as well as lead hour.

## What was not done

- **The sealed holdout was not opened.** It is opened once, when model selection is
  finished.
- **Scenarios are implemented but not scored.** `models/scenarios.py` provides the
  Schaake shuffle and a Gaussian copula; neither is on the leaderboard because marginal
  CRPS cannot distinguish them — that needs variogram and energy scores over the
  delivery-day vector.
- **No hyperparameter search.** Every model uses fixed, deliberately modest settings.
  With ~763 development days, tuning on the same folds used for comparison would buy
  apparent skill and cost real skill.
- **Monotone constraints are only on the point model.** LightGBM rejects them under both
  the `quantile` and `l1` objectives; only squared error accepts them.

## Reproducing

```bash
PYTHONPATH=research/src uv run python -m renewable_forecast.pipelines.train
PYTHONPATH=research/src uv run mlflow ui --backend-store-uri sqlite:///research/mlruns/mlflow.db
```
