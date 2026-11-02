# Forecast publication contract

This defines forecast identity, delivery eligibility and scoring rules for the
SE3 checked-generation workflow and older manual archives. For operating status,
see the [roadmap](../ROADMAP.md); for execution, use [operations](operations.md).

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

The legacy manual archives and SE3 checked-generation workflow share these timing
principles. Their delivery authority differs as described below:

| Field | Meaning |
|---|---|
| `forecast_id` | Unique identity of one complete issued forecast |
| `issue_time` / `information_cutoff_at` | Intended information cutoff: 09:00 UTC D-1 |
| `run_started_at` | Actual start of generation |
| `created_at` | Actual completion of the forecast rows |
| `published_at` | SE3: confirmed delivery time after a complete public generation becomes readable; older manual path: archive publication time |
| `publication_deadline_at` | 09:30 UTC D-1 |
| `publication_status` | On time, late, early, retrospective or legacy unverified; new SE3 receipts can remain `pending_delivery` after an interrupted confirmation |
| `is_primary` | First eligible on-time issue for this product/day |
| `revision_of` | Original eligible forecast, if this is a later revision |
| `model_version` | Resolvable source/configuration identity |

All timestamps are timezone-aware UTC. A revision retains the original cutoff,
receives a new forecast ID and never replaces the forecast used for scoring.
An intended issue timestamp alone does not prove on-time publication.

For SE3, `live.publish` first commits complete checked files and then confirms
their receipt in the public pointer. A crash between those steps stays unverified;
recovery uses its actual later confirmation time. `live.eligible_receipts` selects
the first confirmed on-time issue, not an older archive's local `is_primary` flag.
Manual German archive timing does not by itself prove website delivery. These
distinctions prevent a retry/recovery from inventing on-time evidence.

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

The SE3 workflow saves trained main/reference models, exact training inputs and
lag history, code/settings/environment identities, training cutoff and reload
fixtures. Validation and explicit promotion precede prediction; stale, changed,
wrong-issue or post-cutoff models are rejected. This is implemented in
`saved_models.py` and exercised locally; live production acceptance is pending.
German manual commands still fit during prediction. Source relocation must not
rewrite original model records or reopen evaluation windows. The daily SE3 policy
is a new forward version, not a new accuracy evaluation of the frozen release.

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
- The new SE3 comparison collector explicitly requests A69/**A18** at 08:55 UTC.
  Only a complete wind curve with raw/parsed hash evidence received before the
  cutoff is eligible; it is not an A01 historical latest-vintage replacement or
  an input to our model. Missing comparison data leave its score unavailable.

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
