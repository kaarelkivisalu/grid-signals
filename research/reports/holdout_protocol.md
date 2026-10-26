# Final renewable evaluation — frozen procedure

Candidate: the corrected quarter-hour SE3 wind model (hourly repeated) and native
DE-LU solar model already selected on the winter development folds. Configuration
and source hashes are frozen in `configs/releases/renewables_2026_10_15.json`
before any final score is produced.

- Delivery window: 2026-03-20 through 2026-09-19 inclusive (184 requested days).
- Refit on March 20 and each following month start. Each fit uses only delivery
  days strictly before its origin minus seven days; subsequent months may use
  earlier holdout observations as a normal rolling production simulation.
- Keep all eligible complete delivery days. Report scored days and intervals.
  Missing weather or observations exclude a whole delivery day, never selected hours.
- Compare the selected model with physical wind / physical solar and smart solar
  persistence on identical rows. Solar marginal scores use elevation above 5 degrees.
- Fixed model/calibration parameters; 19 quantiles. Four CPU threads per booster.
- Record CF MAE, CRPS, bias and interval coverage. No adjustment based on final results.
- Checkpoint predictions per task/origin. An interrupted run resumes the identical
  frozen release; a completed result is returned without refitting or rescoring.
- This final evaluation does not replace the separate forward operational trial.

The runner rejects modified frozen source/configuration files. Its entry point is
`python -m renewable_forecast.pipelines.holdout`.

## Recorded harness correction — October 15

The initial solar fold stopped before writing any predictions: its physical
reference received 73 missing daylight training-weather rows and returned
non-finite values. The holdout runner had omitted the complete-day training filter
already used by the corrected development evaluator. Amendment 1 restores that
same filter, preserves wind checkpoints and leaves model/calibration settings
unchanged. The original release manifest remains intact; the amendment records
both runner hashes and its reason. No final solar score informed this correction.
