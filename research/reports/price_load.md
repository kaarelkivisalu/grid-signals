# Price input experiment: custom load

Joint development comparison, May-August 2026. Out-of-sample upstream predictions; identical downstream train/test rows. No independent final claim.

| Inputs | Days / 123 | MAE EUR/MWh | CRPS EUR/MWh | 80% coverage | CRPS delta 95% CI |
|---|---|---|---|---|---|
| custom_load_point | 123 | 25.89 | 20.33 | 62.4% | -0.45 to +0.02 |
| custom_load_quantiles | 123 | 26.01 | 20.44 | 62.7% | -0.37 to +0.15 |
| price_only | 123 | 26.16 | 20.55 | 62.5% | +0.00 to +0.00 |

Upstream configuration selected in load development; historical load revisions assumed. New forward data required for confirmation.
