# Price input experiment: custom load

Declared October 15 before producing the comparison.

Question: does adding the custom load forecast improve the existing price-only
quantile GBM on matched development dates?

- May–August 2026, four monthly price refits with a seven-day embargo.
- Fix the upstream direct-quantile load model and the existing price GBM parameters.
  The load model was selected during load development; this is a joint development
  experiment, not an independent test of a newly selected modelling chain.
- Generate October 2025–August 2026 load inputs out of sample, using monthly load
  refits trained strictly before each origin minus seven days. Save fold origins,
  maximum training day and source information cutoff with each prediction.
- Price training uses only previous out-of-sample load forecasts, never fitted
  values or realised future load. All price arms use the same complete native
  quarter-hour training and test rows.
- Compare price-only inputs, added load median, and added load 10/50/90% quantiles.
  Use the same price GBM and fixed parameters; no hyperparameter search.
- Report EUR/MWh MAE, CRPS, coverage and paired day-block CRPS differences against
  the matched price-only arm. Report requested/scored days.
- Historical actual-load revision assumptions carry through from load_protocol.md.
  Source training cutoffs are necessary evidence, not a claim that historical
  first-publication actual values have been recovered.
- Do not reopen September–October price outcomes as another independent test.
  Any selected follow-up needs a declared forward experiment from October 16 onward.
