# Final renewable diagnostics

Post-evaluation analysis of fixed predictions, without changing any model. Bias is actual minus forecast; negative means overprediction. Solar uses daylight rows.

## wind_onshore

Paired day-block 95% bootstrap interval for CRPS difference versus physical_power_curve: **-0.800 to -0.564 percentage points of capacity**. Negative favours the quantile model.

Missing complete delivery days: 2026-06-24, 2026-09-03.

| Month | Days | nMAE | Bias | 80% coverage |
|---|---|---|---|---|
| 2026-03 | 12 | 2.86% | -0.07% | 82.1% |
| 2026-04 | 30 | 2.73% | +0.00% | 83.0% |
| 2026-05 | 31 | 2.40% | +0.29% | 78.9% |
| 2026-06 | 29 | 2.36% | +1.02% | 78.9% |
| 2026-07 | 31 | 2.28% | +0.98% | 84.2% |
| 2026-08 | 31 | 2.30% | +1.16% | 79.1% |
| 2026-09 | 18 | 2.62% | +0.93% | 82.5% |

## solar

Paired day-block 95% bootstrap interval for CRPS difference versus solar_physical: **-1.020 to -0.567 percentage points of capacity**. Negative favours the quantile model.

Missing complete delivery days: none.

| Month | Days | nMAE | Bias | 80% coverage |
|---|---|---|---|---|
| 2026-03 | 12 | 2.62% | -1.86% | 88.2% |
| 2026-04 | 30 | 2.91% | -1.85% | 79.7% |
| 2026-05 | 31 | 2.80% | -2.21% | 77.6% |
| 2026-06 | 30 | 2.59% | -2.01% | 83.0% |
| 2026-07 | 31 | 2.88% | -2.35% | 80.5% |
| 2026-08 | 31 | 3.09% | -2.68% | 76.5% |
| 2026-09 | 19 | 2.85% | -0.70% | 86.0% |

Aggregate interval coverage is close to nominal while monthly coverage and bias vary. The solar median overpredicts on average: fleet assumptions and weather/model bias are hypotheses to investigate, not established causes.

Any corrective experiment needs a new declared development/forward window. These final outcomes cannot become another tuning set.
