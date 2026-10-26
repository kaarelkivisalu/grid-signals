# Final DE-LU load evaluation

Release load_2026_10_15; 2026-09-01 through 2026-10-15 exclusive. Development-selected candidate: **load_quantile_gbm**.

Frozen input matrix and fixed source/configuration hashes. Monthly refits, seven-day embargo. No tuning after final evaluation. Historical actual-lag revisions remain an explicit assumption.

| Method | Days / requested | MAE MW | CRPS MW | 80% coverage | Relative MAE |
|---|---|---|---|---|---|
| load_quantile_gbm | 44 / 44 | 1433.4 | 1069.6 | 79.7% | 0.821 |
| load_point_gbm | 44 / 44 | 1545.5 | 1138.4 | 83.2% | 0.885 |
| load_weekly | 44 / 44 | 1746.2 | 1337.6 | 94.0% | 1.000 |
| load_ridge | 44 / 44 | 2100.1 | 1614.8 | 75.2% | 1.203 |

Excluded complete delivery days: none.
