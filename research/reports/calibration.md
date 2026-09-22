# Calibration — roadmap track A

**Run 2026-09-21/22, development set only** (18 folds, 13,082 hours, 546 delivery days,
the same rows as `modelling.md`). The holdout stays sealed. Reproduce with
`PYTHONPATH=research/src uv run --group research python -m renewable_forecast.pipelines.compare_calibration`.

## Diagnostics that set the direction

All four come from the persisted backtest of the previous shipping model.

**1. The high-output shortfall was partly an artefact of how hours were binned.**
The old `coverage_by_output.png` grouped hours by *realised* output. Hours that turned
out high are over-represented among hours the forecast under-shot, so even a
calibrated forecast shows low coverage in the top bins (Lerch et al. 2017). Binned by
the forecast median, the top bin's 80% coverage is 0.719, not 0.696. The figure now
bins by forecast.

| forecast CF | n | cov@80 | cov@90 |
|---|---|---|---|
| 0.0–0.2 | 5,614 | 0.761 | 0.872 |
| 0.2–0.4 | 3,939 | 0.734 | 0.850 |
| 0.4–0.6 | 2,384 | 0.693 | 0.827 |
| 0.6–0.8 | 1,145 | 0.719 | 0.817 |

**2. Both tails are thin, and season shifts them.** Truth fell below p10 on 12.7% of
hours and above p90 on 13.7%. In DJF it fell below p10 on 17% (winter over-prediction).
In SON it fell above p90 on 20% (autumn under-prediction).

**3. NWP model disagreement predicts error that the intervals miss.** Hours were split
into quintiles of raw p10–p90 width, then within each quintile into quartiles of
`power_curve_model_std` (the spread of the three models' power-curve output). Mean
absolute error rose with spread in four of the five width quintiles, roughly doubling in
the narrower ones. 80% coverage fell from 0.81 in the lowest spread quartile to 0.67 in
the highest. Spread–skill exists (the Thorarinsdottir & Gneiting 2010 test), and the
calibration layer, stratified by lead hour and level, could not see it.

**4. Daily errors persist.** The lag-1 autocorrelation of daily mean error is 0.32, and
0.15 at lag 2. This feeds roadmap item D1, not the calibration layer.

## The A/B

The boosters are fitted once per fold on the inner 75% of the training window, and
every arm post-processes the same raw quantiles.

| arm | CRPS | Δ vs stratified (day-block 95% CI) | nMAE | cov@80 | cov@90 | sharp@80 |
|---|---|---|---|---|---|---|
| raw (no calibration) | 0.02373 | +2.3% (significant) | 0.0305 | 0.603 | 0.731 | 0.070 |
| stratified (lead × level, *shipped before*) | 0.02321 | — | 0.0307 | 0.737 | 0.852 | 0.090 |
| **spread_additive (level × spread)** | 0.02327 | +0.3% (n.s.) | 0.0310 | **0.774** | **0.885** | 0.097 |
| spread_scaled (width-normalised) | 0.02343 | +0.9% (n.s.) | 0.0313 | 0.778 | 0.884 | 0.100 |
| spread_scaled_refit | 0.02349 | +1.2% (n.s.) | 0.0313 | 0.766 | 0.875 | 0.097 |

80% coverage by condition:

| arm | spread Q1 | Q2 | Q3 | Q4 | DJF | MAM | JJA | SON |
|---|---|---|---|---|---|---|---|---|
| stratified | 0.766 | 0.739 | 0.743 | 0.699 | 0.734 | 0.777 | 0.781 | 0.697 |
| spread_additive | 0.769 | 0.777 | 0.776 | 0.774 | 0.779 | 0.818 | 0.803 | 0.731 |

## Verdict

**`spread_additive` ships** (`QuantileGBM` now uses `SpreadCQR(normalise=False)`).
CRPS is unchanged within noise, and CRPS is the frozen headline metric. Pooled 80%
coverage moves from 0.737 to 0.774, and it no longer depends on NWP disagreement or on
forecast level. That is the conditional calibration Gibbs et al. (2024) argue for,
reached over pre-chosen groups.

Normalising scores by width did not help, because the spread strata already carry the
heteroscedasticity. Refitting the booster on the calibration days as well made the
intervals too sharp for the correction measured on the inner model, as feared.

**Still open:** coverage is 0.774, not 0.80. The remainder is concentrated in SON
(0.731). The calibration block is the most recent quarter of the training window, and
it is not exchangeable with the test month when the season turns. That is drift, not
stratification, so it needs roadmap A3 (a larger, cross-fitted calibration set) or A5
(a second-stage recalibration that can shift location as well as width).

## A3 — where the calibration residuals come from (2026-09-22)

`compare_calibration --schemes`. Full `QuantileGBM` fits on the configured feature set
(Open-Meteo + MEPS + IFS runs), 17 folds, 12,026 hours.

- **recent**: fit on the oldest 75% of the window, calibrate on the newest 25%.
- **crossfit**: split the window into 4 contiguous day-blocks. Predict each block from
  a model fitted on the other three, calibrate on all out-of-fold predictions, then
  refit on the whole window.
- **crossfit_season**: crossfit, with season added to the strata.

| scheme | nMAE | CRPS | Δ CRPS (day-block 95% CI) | cov@80 | cov@90 | DJF | MAM | JJA | SON |
|---|---|---|---|---|---|---|---|---|---|
| recent | 0.0271 | 0.0205 | — | 0.765 | 0.875 | 0.762 | 0.805 | 0.792 | 0.727 |
| **crossfit** | **0.0262** | **0.0198** | **−3.7%** [−0.0011, −0.0004] | **0.784** | **0.893** | 0.760 | 0.813 | 0.808 | **0.779** |
| crossfit_season | 0.0272 | 0.0207 | +0.9% (n.s.) | 0.735 | 0.848 | 0.708 | 0.783 | 0.781 | 0.710 |

(The season columns are 80% coverage.)

**Crossfit ships** (`configs/base.yaml: model.quantile.calibration`). It is the first
calibration change that also improves accuracy, and for two reasons at once. The
calibration set now spans every season, so an October forecast is no longer calibrated
only on summer residuals: SON coverage goes from 0.727 to 0.779. And the final boosters
see the most recent quarter of the window, which `recent` withheld: nMAE −3%. The cost
is five fits instead of one.

Season as a stratum hurt. Each season × level × spread cell holds too few independent
*days*, even though it holds enough rows, so the per-cell corrections chase noise.

Remaining bias by season (median, CF): DJF −0.0065, MAM −0.0056, JJA +0.0046, SON
+0.0089. It is smaller than before, but still a level shift that calibration does not
touch. It is tested separately as a feature question (does the model over-learn
day-of-year?).
