# Final renewable holdout

Frozen release: renewables_2026_10_15. Delivery 2026-03-20 to 2026-09-19.

Monthly rolling refits with a seven-day embargo. No retuning after this evaluation.

## wind_onshore

| Model | Days / 184 | nMAE | CRPS | 80% coverage |
|---|---|---|---|---|
| physical_power_curve | 182 | 3.28% | 0.02519 | 83.3% |
| quantile | 182 | 2.46% | 0.01839 | 81.1% |

## solar

| Model | Days / 184 | nMAE | CRPS | 80% coverage |
|---|---|---|---|---|
| quantile | 184 | 2.84% | 0.02076 | 80.6% |
| smart_persistence | 184 | 5.44% | 0.04200 | 85.5% |
| solar_physical | 184 | 3.48% | 0.02882 | 82.3% |
