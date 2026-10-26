# Forecast publication contract

**Status:** the read-only portfolio demo and local Parquet publication trial are
implemented. The [target architecture](../../docs/implementation-plan.md) uses
publishing Parquet and other result files, a result-reading website and a Prefect-operated
forecast lifecycle. A downstream database/API feed is not a planned requirement.
Displaying research snapshots does not establish reliable daily delivery.

## Operational gate

Require approximately **30 consecutive scheduled daily issues per product** with
near-total on-time success. Report all due issues, including missing and failed
runs. Two products issued on one day do not count as two days of reliability.

Investigate live error above roughly 1.25 times the relevant backtest error at
matched leads. Compare season, output regime, input coverage and baseline-relative
skill before diagnosing train/serve skew: a winter aggregate is not an adequate
sole reference for an autumn trial. Assess bias and interval coverage as well as
point error. Historical replay cannot establish operational reliability.

## Identity and timing

The current archive implements these semantics; package and orchestration changes
must preserve them:

| Field | Meaning |
|---|---|
| `forecast_id` | Unique identity of one complete issued forecast |
| `issue_time` / `information_cutoff_at` | Intended information cutoff: 09:00 UTC D-1 |
| `run_started_at` | Actual start of generation |
| `created_at` | Actual completion of the forecast rows |
| `published_at` | Actual archive publication time |
| `publication_deadline_at` | 09:30 UTC D-1 |
| `publication_status` | On time, late, early, retrospective or legacy unverified |
| `is_primary` | First eligible on-time issue for this product/day |
| `revision_of` | Original eligible forecast, if this is a later revision |
| `model_version` | Resolvable source/configuration identity |

All timestamps are timezone-aware UTC. A revision retains the original cutoff,
receives a new forecast ID and never replaces the forecast used for scoring.
An intended issue timestamp alone does not prove on-time publication.

## Forecast files and model versions

Published forecast files retain the metadata above plus zone, fuel/target,
units, resolution, delivery day, interval bounds and quantile values. There is at
most one primary eligible forecast per `(zone, target, resolution, issue_time)`.
Renewable results retain their capacity factor and installed-capacity denominator;
prices retain EUR/MWh and negative values. Current models issue 19 quantiles from
0.05 through 0.95; extra tails require explicit implementation.

Preserve the append-only archive and original eligible forecast across retries
and revisions. Do not confuse a scheduler retry with a replacement for a scored
issue. Model versions and original code and input files must remain recoverable.

The code-reorganisation milestone also introduces saved trained models and
model version records listing the code/settings, training cutoff and reasons for
approving each model. This is target work, not an existing reload/promotion guarantee. Source
relocation must not rewrite the original model version records or reopen evaluation
windows. A future database or public API would require a separate justified design.

## Input and output guarantees

- Complete market delivery days, including 23/25-hour DST days; resolution and
  native versus repeated-hourly semantics accompany every forecast.
- Input observations arrive within the declared latency policy; actuals and
  capacity have stable zone/fuel definitions and units.
- Swedish ENTSO-E A68 capacity is national, so SE3 needs its declared fleet split.
- Public forecasts require producer, process, publication/retrieval timestamps,
  raw-response evidence and complete target coverage before benchmark eligibility.
- A69/A01's documented reference is fixed at 18:00 Brussels time, later than our
  cutoff. Its historical response is not automatically a matched benchmark;
  high apparent accuracy alone does not prove a revision mechanism.

## Failure behaviour

Retain and label late, missing and failed issues. A downstream consumer may use a
complete public fallback only if its availability and target definition are
verified at that consumer's decision time. Otherwise report unavailable. Do not
silently substitute a later public curve or score a retrospective reconstruction.
The website keeps historical results visible with their underlying dates.

## Interpretation that travels with the data

Development scores support model selection; final evaluation and subsequent live
scores provide separate evidence of generalisation and operation. Report scored
versus requested days. Renewable final aggregate coverage is close to nominal;
price intervals under-cover. Neither establishes calibrated guarantees for each
regime. Fleet availability, weather age and capacity assumptions
remain limitations; conservative source timing does not prove an accuracy floor.

Renewable and load forecasts are potential price inputs. Their added value must
be established against a price-only baseline with out-of-sample upstream inputs.
Residual-load and price uncertainty require an appropriate joint/scenario model;
marginal quantiles do not propagate automatically through subtraction or pricing.
