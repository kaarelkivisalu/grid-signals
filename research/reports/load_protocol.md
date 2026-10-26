# DE-LU load protocol

Declared before computing model scores, October 15, 2026.

- Target: ENTSO-E A65/A16 actual total load for DE-LU, in MW, including losses
  and excluding storage absorption. Native quarter-hour observations only.
  Do not expand hourly targets, bridge missing hours or assume 96 intervals on DST days.
- Information cutoff: 09:00 UTC D-1. Use 72/168-hour actual-load lags with an
  explicit 24-hour assumed publication delay. Historical actuals are latest retrieved
  revisions, not preserved first publications: this is a historical reconstruction
  with a stated revision assumption, not a fully vintage-verified operational test.
- Temperature: existing pinned ECMWF IFS 0.25-degree Previous Runs archive at the
  six declared German sites. Use the smallest safe whole-day information age for
  both interpolation endpoints; no realised weather or automatic model blend.
  Equal-area temperatures are an initial spatial approximation, not population weights.
- Calendar: local quarter-hour, day of week, annual phase and known German national
  holidays. Regional and Luxembourg-specific holidays remain omitted.
- Development: May 1–August 31, 2026. Final load window: September 1–October 14.
  The load target is separate from the existing renewable and price experiments.
- Monthly refits, seven-day embargo, trailing two-year training history.
  All methods score identical complete days with full targets, weather and weekly lag.
- Four fixed references: weekly seasonal naive; temperature/calendar/lagged-load
  ridge regression; median LightGBM with training-only residual quantiles;
  direct quantile LightGBM. No parameter search.
- Linear/point uncertainty: last 30 training days, predicted out of sample, then
  refit the point model on all training days. No test-day calibration.
- Report MW MAE/RMSE/bias, CRPS, interval coverage, relative MAE to weekly naive,
  scored/requested days and paired day-block bootstrap CRPS differences.
  Optional nMAE uses each fold's training mean load, explicitly unlike renewable
  installed-capacity normalisation.
- Freeze source/configuration hashes before the final load evaluation. No tuning
  after that result; further changes need a separately declared forward experiment.
- Keep public day-ahead load forecasts outside the matched leaderboard until
  original issue-time eligibility is established. Load minus wind/solar is only a
  residual-load product after all component definitions and complete inputs match;
  separate marginal quantiles cannot simply be subtracted.

Source: [ENTSO-E detailed data definitions, total load pp. 18–20](https://eepublicdownloads.entsoe.eu/clean-documents/Transparency/MoP_Ref2_DDD_v3r4.pdf).
