# Grid Signals roadmap

**Direction agreed 2026-10-26.** This is the authoritative product direction and
delivery order. The [target architecture and implementation plan](docs/implementation-plan.md)
describes the shared package, services and implementation constraints; research reports
retain their own frozen evaluation protocols.

## Purpose and public features

An employer-facing portfolio for energy-sector ML and data science: **Nordic/Baltic
day-ahead wind, solar and spot-price forecasts, credible model comparisons and an
honest public record of publication and performance**. Machine learning, one
bounded deep-learning comparison and practical orchestration/MLOps are explicit
portfolio goals. The website makes that work assessable.

The public experience should answer: what was forecast, what was knowable at issue
time, how it compared with credible alternatives, and whether it arrived on time.

| Public feature | Visitor outcome | Current position |
|---|---|---|
| Forecast explorer | Inspect predictions, uncertainty, actuals and errors by market, date, target and model; download results | Implemented locally for existing research outputs |
| Performance evidence | Compare models on matched data; distinguish development, final evaluation and forward results | Historical comparisons and new forward record implemented; live deployment pending |
| Methods, data sources and timing | Understand inputs, cutoffs, resolution, assumptions and limitations | Implemented locally; presentation must follow the regional direction |
| Daily publication record | See latest forecasts, freshness, missing/late/failed issues and subsequent scores | Saved-model record verified locally; server cutover and always-on delivery pending |
| Regional coverage matrix | See separate observation, evaluation and publication status for every zone and target | Existing map shows data/model coverage; the regional matrix remains work |
| Research case studies | Assess SE3-to-SE4 transfer and one deep-learning challenger, including negative results | SE3 research exists; transfer and challenger remain work |

Agent/RAG integration is a later usefulness evaluation, not a promised chatbot.
Choose a task and success measure before selecting an AI approach or adding a
public feature. The original generic chat and briefing product has been retired.

## Coverage destination

Cover all **15 bidding zones**: **SE1–SE4, NO1–NO5, DK1–DK2, FI, EE, LV and LT**.
For each, deliver evaluated **onshore wind, solar and day-ahead spot-price**
forecasts with a publication record. Offshore wind follows as a separate milestone
where generation exists. Iceland and expansion beyond these zones are outside
this roadmap.

SE3 wind leads the initial demo. Retain German solar/load/price results as
supporting case studies; completing the German forecasting chain is not the main
destination. Imported observations alone never count as forecast coverage.

Every zone/target has separate observation, research evaluation and publication
statuses. Missing or unsuitable targets remain explicit blockers, not completed
coverage. Distinguish absent generation from missing measurements, especially for
small or behind-the-meter solar fleets and offshore wind.

## Ordered milestones

Read the [architecture and implementation constraints](docs/implementation-plan.md)
before implementing a milestone. Work on one milestone at a time; current work
is the manual deployment and live acceptance of 2b.

### 0. Establish direction — complete

Audience, public features, the 15-zone destination and delivery order are agreed.
The [architecture](docs/implementation-plan.md) records implementation constraints;
[historical decisions](docs/archive/implementation-history.md) preserve the assessment.

### 1. Publish the historical demo — complete

The [test site](https://grid-signals-demotest.kaarelkivisalu.ee) was deployed and
passed anonymous desktop/phone acceptance on 2026-11-01: historical forecasts,
methods, matched comparisons and CSV downloads are accessible independently of
production. The [deployment record](docs/archive/operations-record.md#public-hosting)
retains the commit, image digests and checks.

Deploy from `feat/electricity-forecasting` while completing the roadmap. After
owner approval to merge into `main`, switch to `https://grid-signals.kaarelkivisalu.ee`.
Keep the existing Dokploy hosting unless a concrete capacity/cost issue warrants change.

### 2. Bring the code together and run daily SE3 forecasts

**2a — One product: complete (2026-11-01).** One installed
`grid_signals.forecast` package and `grid-signals` CLI own forecasting. The original
market-database/chat application is retired and standalone exercises moved out.
Original source/data and frozen evidence were preserved; fixed-input predictions,
metrics and exports were checked against the consolidated package. See the
[preservation record](docs/archive/operations-record.md#preservation-and-source-consolidation--2026-11-01).

**2b — Implementation verified; owner deployment pending (2026-11-01).**

- [x] Implement the shared Prefect lifecycle, with model preparation separate
  from deadline-sensitive prediction and explicit validation/promotion.
- [x] Implement checked complete delivery, first-publication receipts, visible
  due/missing/late/failed issues, matched scores, bias and interval coverage.
- [x] Verify the local lifecycle, web/runner images, restart and backup restoration.
- [ ] Provision and seed the always-on producer; verify host resources and restart behaviour.
- [ ] Prepare a model in the deployed environment, preview the new web service,
  disable old workstation timers, then activate Prefect schedules.
- [ ] Verify current public forecasts and subsequent scores, domain cutover
  and off-host backup recovery.
- [ ] Monitor provider failures and establish live evidence that timeout handling works.
- [ ] Assess the approximately 30-consecutive-issue reliability gate.

[Local verification](docs/archive/operations-record.md#local-verification--2026-11-01)
passed 315 tests (2 skipped), lint/formatting, offline images, browser checks and
isolated Prefect restart/restore. These checks do not establish host capacity,
live deadline performance or resolution of the original provider timeout cause.
The new daily saved-model policy is a separate forward version from frozen research.

**Next action:** the owner follows the [manual deployment steps](docs/operations.md#manual-deployment-steps).
Schedules default to paused; old workstation timers remain active on preserved
2a source until cutover. Never run both schedule owners for the same issues.

**Done when:** current SE3 forecasts and subsequent scores reach the public site
automatically, failures/stale data remain visible, and live acceptance above holds.
Use the [publication contract](docs/integration_contract.md#operational-gate) before
claiming dependable operation. Prefect and MLflow complement the public record;
German case studies do not require new production schedules. Do not start SE4
transfer before deployment acceptance.

### 3. Transfer onshore wind to SE4

- [ ] Audit targets, fleet/capacity definitions and issue-time weather availability.
- [ ] Adapt existing product restrictions and result-file and settings paths only
  as needed for SE4; preserve existing SE3 and German releases.
- [ ] Reuse the SE3 approach and references; freeze the comparison before evaluation.
- [ ] Publish matched results, transfer limitations and the model decision.
- [ ] Add validated SE4 forecasts to daily publication and the coverage matrix.

**Done when:** visitors can compare SE3 and SE4 evidence and inspect SE4's own
publication record. A positive improvement is not required for an honest case study.

### 4. Compare one deep-learning challenger

- [ ] Use an established wind task; predeclare one challenger, compute budget,
  evaluation protocol and promotion criteria before training.
- [ ] Publish point/probabilistic skill, runtime and operating implications.
- [ ] Retain the serving baseline unless the challenger earns promotion.

**Done when:** the demo presents a reproducible comparison and an evidence-based
adoption decision, including a negative result if the challenger loses.

### 5–7. Complete regional coverage, one zone/target at a time

| Milestone | Default delivery sequence | Completion criterion |
|---|---|---|
| **5. Onshore wind** | After SE3 and SE4: FI → DK1 → DK2 → EE → LV → LT → SE2 → SE1 → NO1 → NO2 → NO3 → NO4 → NO5 | All 15 zones have evaluated onshore forecasts and public publication records |
| **6. Solar** | DK1 → DK2 → EE → LV → LT → FI → SE4 → SE3 → SE2 → SE1 → NO1 → NO2 → NO3 → NO4 → NO5 | All 15 zones have evaluated solar forecasts and public publication records |
| **7. Day-ahead spot prices** | FI → EE → LV → LT → SE4 → SE3 → SE2 → SE1 → DK1 → DK2 → NO1 → NO2 → NO3 → NO4 → NO5 | All 15 zones have evaluated price forecasts, credible references and public publication records |

For **each increment**: audit data → freeze evaluation → compare models → publish
results and limitations → add daily publication → update the demo and coverage
matrix. A blocked zone remains incomplete; record the evidence and next action
before moving to the next ready zone. Reorder only through a documented
data-readiness decision, not by silently dropping difficult markets.

Incremental expansion must also cover the source-zone mappings, fleet adapters,
market-day/timezone convention, configuration, result-file paths, scorer, exporter
and website inventory. Several current functions are explicitly SE3- or DE-LU-only;
the application's 15-zone registry does not make them regional forecasting pipelines.

Start solar with a DK1 pilot, using the existing German work as a reference. Start
regional prices with a FI pilot using the existing price benchmark framework.
Price-only benchmarks do not require every custom renewable model first. Add load,
neighbouring-market or other inputs only for a specific experiment; promote them
through matched out-of-sample evidence. Wind/solar skill does not establish price
skill, and marginal quantiles do not automatically give residual-load uncertainty.

### 8. Add offshore wind where applicable

- [ ] Audit applicable zones and separate absent generation from missing data.
- [ ] Add evaluated offshore forecasts and daily publication one zone at a time.
- [ ] Expose component and total-wind views with consistent definitions; validate
  any combined uncertainty rather than adding marginal quantiles.

**Done when:** every applicable regional zone has an evaluated offshore product and
publication record, with non-applicable and blocked cases explicitly distinguished.

### 9. Evaluate useful agent/RAG integration

- [ ] Identify a recurring visitor task using the working forecast demo.
- [ ] Compare one bounded AI approach with the existing interface or a simpler alternative.
- [ ] Measure correctness, evidence retrieval/citations, abstention, latency and cost.

**Done when:** there is a justified public-feature proposal or a documented decision
to defer. Select the use case at this milestone; do not add AI solely for breadth.

## Delivery discipline and boundaries

- One major milestone and one zone/target increment at a time. Improve the public
  demo, update status and pass relevant checks before starting the next addition.
- Fix usability/reliability problems in the delivered demo before expanding scope.
- Keep development, final and forward evidence separate. Preserve frozen releases
  and immutable first-eligible forecast identities; do not reopen holdouts for tuning.
- Handle market-local delivery days, DST, units, source resolution and actual
  publication timing explicitly. Do not replace missing issue-time inputs with later data.
- Keep training outside page requests. Use one product package, Parquet and saved result
  files and a result-reading app. The original market database is retired; no public
  API or frontend rewrite is required for the selected features.
- Preserve scientific evidence and irreplaceable data, not every implementation.
  Remove superseded components after verifying their replacement; Git history
  preserves obsolete code without keeping it in the active operating surface.
- Define each later experiment's implementation when its milestone is reached;
  this roadmap authorises no speculative scaffolding of future features.
- Defer German chain completion, generic chat expansion, alerts, report formats,
  multi-tenancy, authentication, billing, trading execution and further geography.

See the [target architecture and implementation plan](docs/implementation-plan.md),
[operations](docs/operations.md) and [research evidence](research/README.md).
