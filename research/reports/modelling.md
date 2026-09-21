# Phase 5 — Modelling

**Run 2026-09-20, development set only.** The 184-day holdout (2026-03-20 → 2026-09-19)
is **sealed** and is not reported here. 18 rolling-origin folds over 763 development
days, 7-day embargo, resampled by delivery day, on the frozen protocol in
`protocol.md`. All metrics normalised by installed capacity.

## Leaderboard

![](figures/leaderboard_crps.png)

| forecaster | nMAE | nRMSE | nBIAS | CRPS | cov@80 | sharp@80 | CRPSS vs clim. |
|---|---|---|---|---|---|---|---|
| *A69_latest_vintage* | *0.0147* | *0.0242* | *0.0000* | *0.0118* | 0.769 | 0.041 | *+0.900* |
| **lightgbm_quantile** | **0.0307** | 0.0418 | −0.0026 | **0.0232** | 0.737 | 0.090 | **+0.804** |
| lightgbm_point_monotone | 0.0312 | 0.0421 | −0.0019 | 0.0241 | 0.765 | 0.093 | +0.796 |
| physical_power_curve | 0.0357 | 0.0481 | 0.0039 | 0.0272 | 0.778 | 0.107 | +0.770 |
| ridge_sanity_floor | 0.0361 | 0.0475 | −0.0039 | 0.0273 | 0.768 | 0.104 | +0.769 |
| climatology | 0.1632 | 0.2081 | 0.0579 | 0.1182 | 0.743 | 0.455 | 0.000 |
| persistence | 0.1960 | 0.2500 | 0.0010 | 0.1428 | 0.784 | 0.521 | −0.208 |

Every learned model beats climatology significantly (day-block bootstrap on the CRPS
difference, 2000 draws). Persistence is significantly *worse*, as expected at a 48-hour
lag. A69 is italicised because it is a reference, not a bar: ENTSO-E serves the latest
revision, which postdates gate closure. See `protocol.md`.

**Two readings of the board.** The sanity floor passes decisively — ridge on eight
physical features beats climatology by 76.9% CRPS, so nothing downstream is chasing a
pipeline bug. And machine learning earns 15% CRPS over the physical power-curve
baseline: real, significant, and modest. The feature importances say the same thing.

| feature | share of gain |
|---|---|
| power_curve_model_mean | 19.0% |
| power_curve_model_mean_shift−1 | 18.9% |
| power_curve_model_mean_shift+1 / −3 | 7.2% |
| wind_speed_100m_model_mean (+ shifts) | 9.8% |
| day-of-year terms | 4.6% |

## Error against lead time is a step, not a gradient

![](figures/nmae_by_lead.png)

An earlier version of this report said error "grows with lead time, as it must" and
backed it with three coarse lead blocks (0.0263 / 0.0304 / 0.0348). The block averaging
hid the actual shape. Within leads 22–33 error is flat at ~0.026; within 34–46 it is flat
at ~0.035; the transition is a single-hour discontinuity of **+35%**.

Two things change at lead 34 simultaneously:

- **The NWP vintage.** Open-Meteo's Previous Runs API is addressable only in whole days.
  A valid time more than 24 h after the 09:00 UTC issue cannot use `previous_day1`
  without leaking, so `features/assemble.required_offset` correctly switches to
  `previous_day2` — a forecast 24 h older. Confirmed: the offset column flips from 1 to 2
  at exactly lead 34, with no overlap.
- **The clock.** Lead 34 is 10:00 UTC on the delivery day. Leads 22–33 are night and
  early morning; 34–46 are daylight, when boundary-layer mixing makes wind genuinely
  harder to forecast.

The two are perfectly collinear under a fixed issue time, so the leaderboard alone cannot
separate them. **A69 is the natural control** — it is a TSO product with no Open-Meteo
vintage switch, and it crosses lead 34 with no step at all, rising smoothly across the
whole window. That points at the vintage.

This is not leakage; the offset switch is the conservative choice and the leakage test
passes. It is *cost*: the back half of every delivery day is forecast from a run a full
day older than the physics requires. A genuine 00z run covers +22…+47 h in one
initialisation.

**Consequence.** Fixing it needs an NWP archive addressable by run initialisation rather
than by whole days. Probed and confirmed: Open-Meteo offers no such parameter
(`*_previous_run1` is rejected). MET Norway's MEPS archive is run-addressed, which
promotes `meps_archive.md` from an ensemble nice-to-have to the fix for the largest
measured structural error in the model.

## Winter is the hard season, and the bias says why

![](figures/seasonal_bias.png)

`nBIAS = mean(actual − predicted)`, so DJF's −0.0138 means the model **over-predicts** in
winter: the forecast says windy and the fleet delivers less. That is the signature of
icing — the NWP is right about the wind and wrong about what the turbines do with it. The
icing proxies in the feature set clearly do not capture it, which moves an explicit icing
model from "nice to have" to the largest identified residual.

## The calibration defect, and its fix

![](figures/calibration.png)

The first leaderboard was uncalibrated, and the coverage column diagnosed itself: the
tighter a model fitted its training data, the worse its intervals.

| forecaster | cov@80 before | after |
|---|---|---|
| lightgbm_point_monotone | **0.327** | 0.765 |
| lightgbm_quantile | 0.612 | 0.737 |
| ridge_sanity_floor | 0.762 | 0.768 |
| physical_power_curve | 0.784 | 0.778 |

Every dressed forecaster was estimating its residual distribution on the rows it had just
been fitted to, and in-sample residuals for a boosted tree are tiny and meaningless out
of sample. The physical baseline looked fine only because an affine correction cannot
overfit. Each training window now reserves its most recent quarter — split by whole
delivery days — for estimating spread, and the quantile model is conformalised on those
held-out days. The point model's CRPS *improved* as a result (0.0267 → 0.0241): honest
intervals score better, not worse.

**Residual gap.** `lightgbm_quantile` is still underdispersed at 0.737 against a nominal
0.80, and its PIT histogram is visibly U-shaped. Likely cause: a 25% calibration slice of
a rolling window is small, and its most recent days are not exchangeable with the test
month. Untried: a larger calibration fraction, the adaptive-conformal online update that
`models/conformal.py` provides but the pipeline does not yet drive, and stratifying by
season as well as lead hour.

## Not done

- **The sealed holdout was not opened.** It opens once, when model selection is finished.
- **Scenarios are implemented but not scored.** `models/scenarios.py` provides the
  Schaake shuffle and a Gaussian copula; marginal CRPS cannot distinguish them, which
  needs variogram and energy scores over the delivery-day vector.
- **No hyperparameter search.** Fixed, deliberately modest settings everywhere. With 763
  development days, tuning on the comparison folds would buy apparent skill and cost real
  skill.
- **Monotone constraints only on the point model.** LightGBM rejects them under both the
  `quantile` and `l1` objectives; only squared error accepts them.

## Reproducing

```bash
export PYTHONPATH=research/src
uv run python -m renewable_forecast.pipelines.train
uv run python -m renewable_forecast.reporting.figures
uv run mlflow ui --backend-store-uri sqlite:///research/mlruns/mlflow.db
```
