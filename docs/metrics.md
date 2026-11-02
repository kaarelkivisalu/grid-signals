# Metrics and evaluation populations

Use this guide to interpret current quarter-hour comparisons. The
[research evidence index](../research/README.md) links results and frozen protocols.
The [archived hourly guide](archive/hourly-metrics.md) describes older populations;
its scores predate corrected weather timing and are not current accuracy claims.

## Which rows count?

| Evaluation | Delivery population | Rules and evidence |
|---|---|---|
| Renewable development | December 2025, January and February 2026; wind 79 matched complete days, solar 90 | [Quarter-hour comparison](../research/reports/products_15min.md) |
| Renewable final | March 20–September 19, 2026; wind 182/184 days, solar 184/184 | [Frozen protocol](../research/reports/holdout_protocol.md), [diagnostics and exclusions](../research/reports/holdout_diagnostics.md) |
| Load/price development | May 1–August 31, 2026; 123 complete days | [Load protocol](../research/reports/load_protocol.md), [price protocol](../research/reports/price_protocol.md) |
| Load/price final | September 1–October 14, 2026; load 44/44 days, price 42/44 | [Load results](../research/reports/load_holdout.md), [price results](../research/reports/price_holdout.md) |
| Forward publication | First eligible on-time issues with complete actual delivery days | [Publication contract](integration_contract.md) |

Historical comparisons use monthly refits, a seven-day embargo and train-only
preprocessing/calibration. Later rolling folds can use earlier evaluation-window
observations under the frozen procedure. This differs from daily serving refits.

Compare methods on matched rows and report scored versus requested days.
Quarter-hour delivery days contain 92, 96 or 100 intervals across DST transitions.
Solar headline scores use daylight rows with maximum site elevation above 5°.
Hourly-repeated wind/LEAR forecasts do not establish native quarter-hour skill.

## Units and definitions

The point forecast is q0.50. Probabilistic forecasts have 19 marginal quantiles,
q0.05–q0.95 in 0.05 steps. Renewable scores use capacity factor
`generation_mw / capacity_mw`; load uses MW and prices use EUR/MWh.

| Metric | Interpretation |
|---|---|
| MAE / nMAE | Mean absolute median error; renewable nMAE is a fraction of installed capacity |
| RMSE / nRMSE | Root mean squared median error; gives more weight to large misses |
| Bias | Signed mean error; check the evaluator's sign convention below |
| Pinball loss | Quantile loss; at q0.50 it equals half the MAE |
| CRPS | Distribution score computed over all 19 quantiles with `scoringrules.crps_quantile`; lower is better |
| `coverage_80`, `coverage_90` | Fraction of actuals inside q0.10–q0.90 or q0.05–q0.95; nominal values are 0.80 and 0.90 |
| `sharpness_80` | Width of q0.10–q0.90; interpret alongside coverage |
| PIT | Predictive CDF at the actual; diagnostic of marginal calibration |
| CRPSS | `1 - CRPS_model / CRPS_reference`; zero matches the named reference, negative is worse |

A renewable nMAE of 0.0246 means **2.46% of installed capacity**, not 2.46% of
actual generation. At an illustrative fixed capacity of 4,000 MW it corresponds
to 98.4 MW. For exact MW errors across a changing fleet, score MW rows directly.
Optional load normalisation uses each fold's training mean load. Negative prices
make MAPE unsuitable.

Renewable metric code uses **actual minus forecast** for bias: positive means
underprediction. Load/price evaluators and explorer errors use **forecast minus
actual**. Do not compare the signs of fields named `bias` without their definition.
See [renewable metric implementation](../src/grid_signals/forecast/evaluation/metrics.py).

## Uncertainty and limitations

Paired confidence intervals resample whole delivery days, not independent
intervals; the default is 2,000 bootstrap draws. Use matched populations and name
the reference. Aggregate coverage close to nominal does not establish calibration
in every season or output regime. Inspect monthly bias, coverage and row counts.

Marginal quantiles are not joint scenarios. Scenario quality needs separate
multivariate scores; quantiles cannot simply be added or subtracted to produce
residual-load uncertainty. Historical holdout results, migration/reload checks
and forward operational evidence answer different questions. Preserve all three
without presenting implementation checks as new accuracy measurements.
