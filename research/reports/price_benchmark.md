# DE-LU day-ahead price benchmark

Price-only development evaluation, 2026-05-01 to 2026-08-31. The separate September to mid-October price holdout is sealed.

Monthly refits; seven-day embargo; two-year training window. Native quarter-hour actual targets, including negative prices. LEAR uses hourly price profiles and repeats its hourly median; it is a price-only adaptation, not an exact reproduction of the exogenous epftoolbox benchmark.

Public fundamentals are excluded because historical publication vintages have not been verified at the 09:00 UTC cutoff.

| Method | Days | MAE EUR/MWh | CRPS EUR/MWh | 80% coverage | Relative MAE |
|---|---|---|---|---|---|
| lear_hourly | 123 | 24.72 | 19.84 | 79.8% | 0.693 |
| lightgbm_quantile | 123 | 26.16 | 20.55 | 62.5% | 0.734 |
| lightgbm_point | 123 | 26.92 | 21.12 | 80.4% | 0.755 |
| seasonal_naive | 123 | 35.66 | 29.14 | 81.2% | 1.000 |

Paired day-block bootstrap CRPS differences are stored with the machine-readable metrics. No MAPE is used around zero or negative prices.
