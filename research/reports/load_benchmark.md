# DE-LU load development benchmark

Window: 2026-05-01 through 2026-09-01 exclusive. Selected by development CRPS: **load_quantile_gbm**.

Monthly refits, seven-day embargo. Historical observations use latest revisions; their original vintages are not verified. See load_protocol.md.

| Method | Days / requested | MAE MW | CRPS MW | 80% coverage | Relative MAE |
|---|---|---|---|---|---|
| load_quantile_gbm | 123 / 123 | 1678.5 | 1299.3 | 66.1% | 0.677 |
| load_point_gbm | 123 / 123 | 1807.1 | 1355.8 | 81.9% | 0.729 |
| load_ridge | 123 / 123 | 2384.3 | 1730.3 | 79.4% | 0.962 |
| load_weekly | 123 / 123 | 2478.0 | 1919.6 | 84.9% | 1.000 |
