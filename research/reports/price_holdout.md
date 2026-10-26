# Final DE-LU price holdout

Frozen release: price_2026_10_15. Window: 2026-09-01 through 2026-10-15 exclusive.

All four fixed methods; monthly refits, seven-day embargo. No tuning after opening.

| Method | Days | MAE EUR/MWh | CRPS EUR/MWh | 80% coverage |
|---|---|---|---|---|
| lear_hourly | 42 | 37.21 | 29.42 | 68.2% |
| lightgbm_point | 42 | 41.38 | 32.74 | 65.5% |
| lightgbm_quantile | 42 | 42.97 | 33.43 | 52.9% |
| seasonal_naive | 42 | 57.89 | 46.81 | 62.6% |

Requested: 44 days. The cached September 13 curve contains 24 hourly values,
so it cannot supply native quarter-hour targets. September 20 also lacks its
complete quarter-hour weekly reference. Both days are excluded for every method;
hourly observations were not expanded to manufacture quarterly targets.
