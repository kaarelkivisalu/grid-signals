# Grid Signals roadmap

**Direction agreed 2026-10-26.** This is the authoritative product direction and
delivery order. The [target architecture and implementation plan](docs/implementation-plan.md)
evaluates the existing code and explains what to combine or remove; research reports
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
| Performance evidence | Compare models on matched data; distinguish development, final evaluation and forward results | Historical comparisons implemented; a visible forward record remains work |
| Methods, data sources and timing | Understand inputs, cutoffs, resolution, assumptions and limitations | Implemented locally; presentation must follow the regional direction |
| Daily publication record | See latest forecasts, freshness, missing/late/failed issues and subsequent scores | Local trial and scorecards exist; always-on delivery is unproven |
| Regional coverage matrix | See separate observation, evaluation and publication status for every zone and target | Existing map shows data/model coverage; the regional matrix remains work |
| Research case studies | Assess SE3-to-SE4 transfer and one deep-learning challenger, including negative results | SE3 research exists; transfer and challenger remain work |

Agent/RAG integration is a later usefulness evaluation, not a promised chatbot.
Choose a task and success measure before selecting an AI approach or adding a
public feature. The original generic chat and briefing product is scheduled for
retirement, rather than kept as a permanent second application.

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

The [whole-project assessment and implementation plan](docs/implementation-plan.md)
evaluates what to keep, consolidate, remove or move. Read it before implementing
a milestone. The target is one forecasting package/CLI and lifecycle across local
use and deployment, with Prefect orchestration and a result-reading website.
Existing code is retained only where it serves that target. Standalone learning
exercises move outside this focused product repository. The architecture is
documented; the code has not yet been combined or removed.

### 0. Establish direction — complete

- [x] Agree the audience, public features, 15-zone destination and delivery order.
- [x] Consolidate active priorities here; mark older direction documents historical.
- [x] Separate existing implementation from unverified deployment and reliability.
- [x] Assess the whole repository and record subsystem ownership, reuse and integration gaps.

This session establishes direction and documentation only. Application changes,
new model experiments and deployment belong to later sessions.

### 1. Publish the historical demo — test site deployed; public UI checks pending

Reuse the existing Streamlit explorer, saved results and standalone demo image.
Open on **SE3 onshore wind with a populated historical comparison**. Keep German
case studies accessible and database-dependent tools outside the public demo.

- [x] Align the default selection and introductory copy with this direction.
- [x] Check that all result files are present; include only the versions listed in the current file index.
- [x] Resolve release checks, including the test that assumes the latest issue is late.
- [x] Confirm the release's commands, dependencies and result files against the
  whole-project assessment; review uncommitted implementation into a reproducible revision.
- [x] Expose only the forecast product. Plan removal of old navigation and runtime
  dependencies without making all backend changes a demo-launch prerequisite.
- [x] Verify the standalone image without database access or API credentials.
- [x] Review the local demo, then hand deployment to the project owner.
- [x] Deploy the test site through Dokploy and verify anonymous HTTPS access.
- [ ] Verify desktop/mobile use, CSV downloads and explicit historical dates on the public site.

Local portfolio review completed 2026-10-26: 407 tests passed, 2 skipped; lint and formatting
passed; the built image passed offline browsing checks and desktop/tablet/phone
review. See the [release review and deployment handoff](docs/operations.md#public-hosting).
The owner confirmed deployment on 2026-11-01 at
[grid-signals-demotest.kaarelkivisalu.ee](https://grid-signals-demotest.kaarelkivisalu.ee).
Anonymous HTTPS requests to the homepage and health endpoint returned HTTP 200;
the health response was `ok`. Public desktop/mobile and download checks remain open.
Deploy from `feat/electricity-forecasting` until the roadmap is reasonably complete.
After the owner approves merging into `main`, switch to
`https://grid-signals.kaarelkivisalu.ee`.

**Done when:** a visitor can inspect forecasts, evidence and methods on the public
site even when forecast production is unavailable. Daily freshness is not a launch
requirement. The test site uses existing Dokploy capacity; reconsider hosting only
for a concrete operational/cost reason. The final domain and merge into `main`
are deferred until the roadmap is reasonably complete.

### 2. Bring the code together and run daily SE3 forecasts

Complete these two parts in order, keeping the demo usable throughout.

**2a — One product:**

- [ ] Save copies of the original code, data and evaluated results before moving code.
- [ ] Bring reusable forecasting code together into the installed package with one CLI,
  product registry and explicit data/output configuration. Local and scheduled runs
  must invoke the same functions.
- [ ] Extract needed mappings/data, then retire the original PostgreSQL market
  application, briefing/chat product, stale commands/scripts and duplicate pages.
- [ ] Move standalone exercises/exploration elsewhere; focused experiments import
  the product package and share its data/evaluation contracts.
- [ ] Reshape dependencies and tests around the retained product; verify fixed-input
  model predictions and metrics before removing superseded implementations.

**2b — Run the forecast workflow:**

- [ ] Replace old Prefect flows with data fetching/checks, training,
  prediction, publishing, scoring and export flows. Use one scheduled runner with
  versioned code and saved models, data and results that survive restarts.
- [ ] Separate model preparation from deadline-sensitive prediction; validate and
  identify saved trained models and training cutoffs before promotion.
- [ ] Provision an always-on producer independently of page serving, with bounded
  retries, resource limits, backup/restore and tested restart behaviour.
- [ ] Cut over to Prefect scheduling and retire local forecast timers and old
  deployment definitions after equivalent lifecycle behaviour is verified.
- [ ] Address observed timeout failures; monitor public forecast collection, forecasting and scoring.
- [ ] Report failures to fetch data, generate forecasts or deliver results in each
  product's job status; a successful task run alone does not prove results were published.
- [ ] Deliver results automatically; publish a complete update at once and keep the last working version if an update fails.
- [ ] Expose every due issue, publication time/status, freshness and available scores.
- [ ] Compare eligible first publications with baselines and track bias/interval coverage.

**Done when:** current SE3 forecasts and subsequent scores reach the public site
automatically, including visible failures and stale data. Assess the existing
[approximately 30-consecutive-issue gate](research/docs/integration_contract.md)
before claiming dependable operation. Prefect run state and MLflow experiment
tracking complement, rather than replace, the public forecast record. German
case-study results do not require continuing all existing German production jobs.

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
  files and a result-reading app. Retire the original market database; no public
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
