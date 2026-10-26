# DE-LU price forecasting protocol

Declared before computing price benchmark results.

- Target: DE-LU SDAC auction clearing price in EUR/MWh. Classification sequence 1;
  09:00 UTC D-1 cutoff. Forecasts retain negative values.
- Development: May 1 through August 31, 2026. Monthly rolling refits, seven-day
  training embargo and a trailing two-year history. Scoring uses complete native
  quarter-hour delivery days on the same rows for every model.
- Separate final price holdout: September 1 through October 14, 2026. This benchmark
  does not open it. Renewable targets/evaluation and their sealed window are separate.
- Hourly SDAC history before October 2025 may train the hourly price-only LEAR
  reference. It is not expanded into artificial native quarter-hour GBM targets.
- References: weekly seasonal naive with training residual quantiles; hourly
  price-only LEAR with AIC-selected LASSO and robust training-only transforms;
  native-quarter-hour median and quantile LightGBM with declared fixed parameters.
- Point-model uncertainty uses the last 30 training days as out-of-sample calibration
  before refitting the point model. Quantile LightGBM intervals are scored as fitted.
- Price lags are masked if their auction curve would not have been published before
  cutoff; this matters for UTC lags across a 25-hour local delivery day.
- Current features: lagged prices, complete prior daily hourly profiles and calendar.
  Historical load/renewables are excluded until matched-cutoff provenance is verified.
- Metrics: MAE/RMSE, CRPS, bias, interval coverage and relative MAE to the weekly naive.
  Report paired day-block bootstrap CRPS differences; do not use MAPE.
- No hyperparameter changes after inspecting this benchmark without a new, explicitly
  declared experiment. A development improvement is not an independent final result.

References: [epftoolbox LEAR/DNN](https://epftoolbox.readthedocs.io/en/latest/modules/models.html)
and [SDAC quarter-hour implementation](https://www.entsoe.eu/network_codes/cacm/implementation/sdac/).
