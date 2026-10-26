# Project direction review

**Historical assessment, not the active roadmap.** The
[agreed direction](../ROADMAP.md) now prioritises Nordic/Baltic coverage, SE3-led
demo delivery and SE4 transfer. The German-first expansion, hosting alternatives
and experiment priorities below are retained as background, not current decisions.

Reviewed 2026-10-15 at `7827ba7` on `feat/vre-forecast`, including comparison with local `main` (`a6289a6`). Audience: energy companies hiring for ML, data science and quantitative analysis. This is a recommendation and implementation plan; it does not replace the frozen research protocol or authorise a particular deployment change.

Implementation has since progressed beyond this initial assessment: the local
forecast demo, daily trial infrastructure and price/load benchmarks are implemented.
Custom load improves its own baseline, but its initial downstream price gain is
statistically unresolved. LEAR is the declared forward price baseline.
Use the [target architecture and assessment](implementation-plan.md) and [research results](../research/README.md)
for implementation status; repository observations below describe the reviewed revision.

## Recommended focus

**Grid Signals: reproducible European day-ahead power forecasts, with a public record of what was predicted and how well it performed.**

Make forecasting and evaluation the product. The website demonstrates it; pipelines keep it current; the CLI operates it; an optional language model explains its outputs. These components have a shared purpose when they serve the same forecast lifecycle.

The strongest portfolio story is a complete chain from public data and weather runs to calibrated forecasts, an honest comparison, and a decision-relevant result. Europe-wide coverage is a sensible long-term destination. The next deliverable should be a convincing small version of that destination.

Choose **DE-LU as the first complete price-forecasting market**, while retaining SE3 wind as the existing research case study. DE-LU already has the initial solar model, public German fundamental data and a public price-forecast comparison candidate. Start its price model using eligible public fundamental forecasts; replace those inputs with custom forecasts through controlled experiments. Building every custom upstream model first would postpone the user's most important output indefinitely.

## What the repository already demonstrates

| Area | Evidence | Assessment |
|---|---|---|
| Data engineering | ENTSO-E and weather ingestion, PostgreSQL tables, validation, backfill, Prefect flows, tests | Useful supporting engineering; keep the parts needed for forecast production and evaluation |
| Wind forecasting | SE3 physics features, multiple NWP sources, quantile LightGBM, cross-fitted calibration, rolling evaluation and leakage tests | The strongest established case study |
| Solar forecasting | DE-LU native quarter-hour model, physical PV chain, daylight evaluation | A useful initial product with provisional fleet/capacity assumptions |
| Evaluation | Frozen protocol, day-block bootstrap, matched rows, source-age checks, withheld holdout | The project's main distinction for employers; finish and present this clearly |
| Application | Streamlit market charts, briefings, chat | Displays the older project identity and has no forecast page |
| Operations | Docker/Compose and Prefect deployment definitions | Existing infrastructure can be reused, but it does not yet operate the research forecast |
| Price / custom load | Price is a roadmap item; the application ingests public load forecasts | Substantial work remains; there is no implemented custom price or load model |
| Geographic coverage | Operational predictor explicitly accepts SE3 wind and DE-LU solar only | Europe-wide forecasts require data and model work, beyond adding UI selectors |

The research branch contains the forecasting work; deploying unchanged `main` will not expose it. The Dockerfile copies `src/` and `prefect.yaml`, omits `research/`, and installs without the research dependency group. The research package also relies on checkout-relative paths. Its current outputs are standalone artifacts, not a deployable application feature.

The current corrected evaluation is in [products_15min.md](../research/reports/products_15min.md):

| Task | Current result | Interpretation |
|---|---|---|
| SE3 wind, repeated hourly distributions on a quarter-hour grid | 2.90% capacity-normalised MAE; 72.2% coverage for the nominal 80% interval; 79 winter development days | Useful point skill, intervals still too narrow, no demonstrated native quarter-hour wind skill |
| DE-LU solar | 1.96% capacity-normalised daylight MAE; 75.5% coverage for the nominal 80% interval; 90 winter development days | Promising against the included references; summer generalisation and fleet assumptions remain open |

These percentages use installed capacity as the denominator. They are not percentage errors relative to actual output, and the two tasks' headline values are not directly comparable. The solar test excludes night. The sealed holdout has not been scored. September hourly charts predate the latest weather-age correction and should not appear as current accuracy claims.

I ran the existing tests: **150 application tests passed; 170 research tests passed; 2 research network tests were skipped by default**. Application tests required Docker access for their temporary PostgreSQL container. This verifies the tested code paths, not a production deployment, a rebuilt image or live forecast accuracy.

## Corrections to settle before making stronger claims

### ENTSO-E day-ahead forecasts have a different cutoff

The repository concludes that unusually good A69 accuracy demonstrates post-cutoff revisions. That causal explanation is not established by its diagnostics.

ENTSO-E's official description separates current forecasts from the day-ahead forecast fixed at **18:00 Brussels time**, and says the latter should not be regularly updated after that point. The research source explicitly requests `process_type="A01"`. The documented day-ahead cutoff is later than this project's 09:00 UTC issue time and later than the auction deadline. This alone prevents assuming a matched-information comparison. It does not prove that a particular response was revised after its documented cutoff. See the [official data description, pp. 65–67](https://eepublicdownloads.entsoe.eu/clean-documents/Transparency/MoP_Ref2_DDD_v3r4.pdf).

Retain the conservative exclusion from the pre-auction leaderboard, but describe it as **publication/vintage not verified for our cutoff**. Inspect raw document creation time, revision, process type and retrieval time where available. Capture the current forecast at 09:00 UTC; record a missing benchmark when tomorrow's curve is absent. Do not fill that gap later with the 18:00 series. The proposed A69 fallback also needs the same availability check.

### Intended issue time and actual publication time must be separate

`predict.run()` derives `issue_time` from the requested delivery day and fixes it to 09:00 UTC, even if the command runs later. Re-running the same issue day appends another forecast with that fixed issue time, and `latest()` chooses the newest creation time. This is adequate for research artifacts, but cannot establish an on-time live prediction.

For operational evaluation, store the information cutoff, actual generation/publication timestamps and a unique forecast ID. Distinguish an on-time forecast, a late forecast, a retrospective reconstruction and a revision. Preserve the original eligible forecast when scoring a day. Resolve this with the integration contract's immutable-per-issue semantics before implementing its database schema.

### Finish validation before expanding model complexity

Freeze a current candidate and a predeclared holdout evaluation procedure. Score the sealed holdout once when that procedure is ready; do not keep moving the final evaluation behind another improvement. Do not tune on the resulting score. Add a forward test for later changes.

Run the daily trial in parallel with the demo work. Track on-time delivery, missing inputs, coverage, bias and baseline-relative skill. The existing 30-run integration gate is useful, but a raw 1.25× winter-backtest error threshold is insufficient: compare matched leads, season/output regimes and contemporaneous baselines. A short seasonal trial is not proof of year-round accuracy.

## Website restoration comes first

A read-only request to `https://grid-signals.kaarelkivisalu.ee/` returned **HTTP 404 at 13:30 UTC on 2026-10-15**. DNS and HTTPS worked from the unrestricted request. A missing proxy route or deployment is a plausible explanation, but the response does not identify the failing component. No server/Dokploy logs or configuration were available to this review, so the production root cause remains unconfirmed. The website has not been restored by this review.

There are also confirmed repository problems to address:

- [DEPLOY.md](../DEPLOY.md) and the root README still describe DuckDB/shared volumes. The actual Compose files use PostgreSQL and a shared Docker network.
- The app Compose service depends on the external `grid-signals` network and a `postgres` service deployed separately. PostgreSQL password and service connectivity are absent from the old deployment instructions.
- Dashboard and briefing pages obtain database connections without a useful unavailable-data fallback. Their default dates assume fresh ingestion.
- The home page presents navigation instructions instead of results. The best work is invisible to a recruiter opening the URL.

### Hosting comparison

| Approach | What it requires | Advantages | Tradeoff | Recommendation |
|---|---|---|---|---|
| Repair existing Dokploy + full app | Inspect router/service logs, repair route, verify PostgreSQL and network, redeploy compatible code | Retains the domain and existing interactive app; little hosting migration | Demo still depends on several running services and database freshness | Time-box diagnosis; reuse if the server is maintained and repair is straightforward |
| Streamlit that reads published forecast artifacts, on Dokploy or Community Cloud | Small forecast/results pages, an export bundle and a separate scheduled producer | Reuses Python/Plotly; removes database and forecasting jobs from page requests | Still a running app; managed hosting uses its documented app URL; producer must publish updates separately | Best near-term application shape |
| Static site with exported charts/data on managed static hosting | Export HTML/JSON and a small presentation layer; configure domain and publication | Page serving survives pipeline outages; excellent for case studies and archived evaluation | Some frontend work; no live Python queries/chat; freshness remains the producer's responsibility | Best durable portfolio landing page; add if the small export is quick |

[Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud) offers managed deployment, and its [deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy) documents `streamlit.app` subdomains. [Cloudflare Pages](https://developers.cloudflare.com/pages/configuration/custom-domains/) supports custom domains for a static presentation. These are delivery options for the same artifacts; moving hosting does not solve forecast production.

**Suggested decision:** spend at most half an engineering day establishing why the current domain returns 404. If the existing server is healthy, restore the route and deploy the thin artifact-reading app there. If infrastructure maintenance is the larger problem, use managed Streamlit for the interactive demo and a static portfolio page for the custom domain. Avoid a frontend rewrite as a prerequisite to showing the research.

### First public demo acceptance criteria

1. A visitor sees the SE3 wind and DE-LU solar forecast charts, issue/publication times and development status immediately.
2. A results page shows forecast versus actual, included baselines, date/row counts and calibration. Show a fixed archived example when no current run exists.
3. Missing or stale live data is labelled while historical results remain usable. Page loading never triggers training, paid LLM calls or backfills.
4. The methodology page links to the code, explains weather vintages, the physical baseline, the holdout and limitations.
5. The existing integration gate remains in force for operational forecast consumption. Explicitly distinguish displaying archived research results from integrating a production forecast service; amend the contract to document that distinction before implementation.

Use three primary pages: **Forecasts**, **Performance**, **Methods**. Keep useful market charts as context. Chat and daily generated prose should not lead the visitor experience.

## What relevant commercial companies sell

The following is a comparison of published product capabilities, checked on 2026-10-15. It is not an accuracy ranking; no commercial forecast samples or independent vendor trials were obtained.

| Company / product | Published offering | Relevant lesson for Grid Signals |
|---|---|---|
| [Volue — Day-Ahead Insights / SpotEx](https://www.volue.com/products-and-services/day-ahead-insights) | European spot-price forecasts, market-native time intervals, weather scenarios and cross-border/flow-based modelling; application and API delivery; European horizon up to 90 days | The closest eventual price/fundamentals product reference. Start with one morning horizon and a few zones; neighbouring markets and network constraints eventually matter |
| [Montel — Energy Quantified](https://www.energyquantified.com/features/spot-and-exchange) | Area spot forecasts, uncertainty, sensitivities, neighbouring-market spreads and exchange forecasts | A coherent forecast dataset with uncertainty is more valuable than unrelated dashboard features |
| [Dexter Energy](https://dexterenergy.ai/help/) | Asset-level wind, solar and prosumption forecasts; short-term price signals; quarter-hour power output; REST API and retrieval of historical forecast runs | Forecast vintages, reliability and evaluation are product features. Its asset-level customer data is a different problem from public-data zonal forecasting |
| [AleaSoft](https://aleasoft.com/demand-renewable-energy-generation-market-price-forecasting/) | Demand, renewable production and market-price forecasts over short, medium and long horizons for major European markets | Select one horizon. Day-ahead skill does not establish a long-term investment forecast |
| [emsys renewables](https://emsys-renewables.com/) | Wind/solar generation forecasts at asset and aggregated market levels, alongside VPP and grid-management products | Fleet geography, availability and the generation-to-market interface are commercially relevant; remote control would add a separate product |
| [enspired](https://www.enspired-trading.com/bess) | AI-based battery trading and optimisation considering asset restrictions and multiple revenue streams | This is a downstream consumer of forecasts and an adjacent direction. A later offline decision study can illustrate value without building execution |

My inference from these products: the best portfolio analogue is a **small forecasting and validation service**. The commercially relevant AI work is forecasting, calibration and decision support. A general-purpose chatbot is peripheral to that story. None of the vendor pages establishes that a public-data prototype can match commercial accuracy.

The renewable-to-price direction also has direct research support: a [study of German day-ahead prices](https://arxiv.org/abs/2501.06180) tests probabilistic load/wind/solar inputs and reports improvements over point-input models. Treat that as a reason to run an ablation on this project's data, not an expected improvement guarantee.

## Build a maintained benchmark inventory

“Compare with all existing models and forecasts” should become **a documented inventory plus a representative executable benchmark**. Separate forecasting algorithms, weather models and third-party energy forecasts. They answer different comparison questions.

### Algorithms to implement in order

| Target | Initial benchmark | Later comparison |
|---|---|---|
| Wind | Persistence, climatology, physical power curve, linear correction, current point/quantile GBM | One neural or spatial challenger after transfer and live evaluation |
| Solar | Clear-sky climatology, smart persistence, PV physics, point/quantile GBM | One neural challenger once summer and fleet assumptions are tested |
| Load | Weekly seasonal naive, temperature/calendar linear or GAM model, GBM | A covariate-aware foundation model |
| Price | Seasonal naive, LEAR, LightGBM point and quantile models | Benchmark DNN, then one covariate-aware foundation model |

[epftoolbox](https://epftoolbox.readthedocs.io/en/latest/modules/models.html) provides established LEAR and DNN reference implementations. Adapt explicitly to current interval lengths and inputs; its historical benchmark does not establish performance in the current quarter-hour regime.

[Chronos-2](https://github.com/amazon-science/chronos-forecasting) supports covariate-informed forecasts and is a sensible first foundation-model challenger. [TimesFM](https://github.com/google-research/timesfm) is another candidate; its current documentation distinguishes permissively licensed weights through 2.5 from 3.0 weights restricted to non-commercial, non-production use. Evaluate a pinned release/checkpoint and record its eligible use. Do not make a foundation model a deployment dependency until it demonstrates value here.

For neural/foundation comparisons, separate history-only and weather-informed settings, document pretraining-data overlap where known, and keep future covariates limited to values actually available at issue time. Equal timestamps alone do not make models with different inputs an algorithm-only comparison.

### Public energy forecasts to evaluate

| Source | Applicable target / coverage | Benchmark eligibility work |
|---|---|---|
| [ENTSO-E](https://transparency.entsoe.eu/) | European wind, solar and load, with availability varying by zone | Archive pre-cutoff current forecasts and raw metadata; do not substitute the 18:00 day-ahead wind/solar product |
| [Fingrid dataset 246](https://data.fingrid.fi/en/datasets/246) | Finnish next-day wind, updated once daily; quarter-hour observations in the documented recent history | Strong next-zone candidate. Verify exact issue availability/DST and whether historical records preserve each original daily forecast |
| [SMARD](https://www.smard.de/en) | German wind/solar and load forecasts; derived residual load | Audit cutoff and revisions. Much is sourced from ENTSO-E, so do not count mirrors as independent forecasters |
| [RTE éCO2mix](https://www.rte-france.com/decouvrir-rte/missions/piloter-optimiser-reseau/equilibrer-offre-demande-electricite) | French consumption forecasts, including previous-day and same-day views | Useful in a later France expansion; establish extractable vintages and matching load definitions |
| [Energy-Charts API](https://api.energy-charts.info/) | Public generation/load forecasts and market prices | Identify underlying producers. Its `/price_next_day` is the published auction curve, not a forecast of an unknown auction result |
| [Energyforecast.de](https://www.energyforecast.de/faq) | Publicly accessible price-forecast API with free short-horizon access and market-zone restrictions | Candidate for DE-LU. Capture before results are known: its FAQ says actual prices replace predictions when available. Check historical access, actual API field semantics and permission to archive/display forecasts |

This shortlist is verified discovery, not a claim to have catalogued every European forecast. Extend the inventory through official TSO portals as each zone is onboarded. Commercial products enter only if forecasts can actually be obtained for a permitted matched-cutoff comparison; otherwise mark them as unavailable for scoring.

For every series, record producer, mirror/source, target definition, geography, units, resolution, run/issue/publication/retrieval times, forecast horizon, archive coverage, licence/redisplay status, missingness and eligibility reason. Save unavailable competitors in the inventory rather than quietly removing them from the comparison story.

### Weather comparisons

Use pinned IFS, GFS and ICON as global inputs where their archives support the experiment, MEPS as a Nordic enhancement, and AIFS or appropriate regional models as later candidates. Compare the energy model under each weather source and their combination; meteorological skill alone does not establish energy forecast skill.

The existing IFS single-run adapter already implements an important part of this. Current [Open-Meteo Single Runs documentation](https://open-meteo.com/en/docs/single-runs-api) lists IFS HRES from March 2024 and most other models from April 2026. Verify each required variable and model's actual coverage. This improves future multi-model comparisons, but does not provide a matched 2024–25 archive for every model. The newer period overlaps the sealed holdout: it must not become an extra development set through convenience. Run-addressed data still needs a publication-latency check.

### Scoring rules

Keep the existing rolling-origin evaluation, train-only preprocessing/calibration and paired day-block comparisons. Publish coverage of the requested horizon as well as metrics on complete matched rows; easy-to-forecast survivors must not hide missing difficult days.

- Wind/solar: MW MAE and capacity-normalised MAE, CRPS/pinball, interval coverage/width, bias and seasonal/output/lead breakdowns. Solar has separate daylight and all-hours views.
- Load/residual load: MW MAE, a declared normalisation and probabilistic calibration where applicable.
- Price: MAE/RMSE in EUR/MWh, relative MAE against the stated naive benchmark, pinball/CRPS, and negative-price/spike event scores when probabilities are available. Avoid MAPE around zero and negative prices.
- Distinguish native quarter-hour models from hourly outputs repeated or interpolated to quarter-hours. SDAC's [quarter-hour implementation](https://www.entsoe.eu/network_codes/cacm/implementation/sdac/) makes this a material product difference.

Add economic evaluation later through one reproducible offline decision study with explicit costs, constraints and a perfect-information upper bound. Forecast skill and simulated decision value are separate claims.

## Path from the current models to Europe-wide prices

### First price model: establish the end-to-end task

Set a separate price protocol: DE-LU, tomorrow's auction clearing prices, a fixed pre-auction information cutoff, native quarter-hour output and an explicit historical hourly/quarter-hour policy. Preserve the renewable protocol's sealed holdout.

Build seasonal-naive and LEAR references, then a LightGBM price model with known lagged auction prices, calendar features and eligible public load/renewable forecasts. Add known outages and neighbour-market features when their issue-time availability is established. The current PostgreSQL `total_load` table overwrites forecasts by target period and has no issue dimension, so it cannot by itself reconstruct historical issue-time load forecasts.

Historical public fundamentals without verified pre-cutoff provenance can support exploratory work, but that score must be labelled accordingly. Pair a strict price-only reference with forward collection rather than presenting a leaky historical fundamentals experiment as an operational comparison.

Evaluate three input sets on matched dates: public point fundamentals; custom point fundamentals; custom probabilistic fundamentals. Generate historical custom inputs out of sample, with every upstream fit/calibration restricted to information available at that fold's issue. In-sample upstream predictions would leak into the price model. Ask whether the upstream work improves price forecasts enough to justify its operating cost.

### Complete the fundamentals in the selected market

Add a custom weather/calendar/lagged-load model, then DE-LU wind with onshore/offshore treatment and improved DE-LU solar fleet data. Use global IFS as the portable minimum weather source and regional models as enhancements. Keep the established SE3 wind model in operation and test transfer to SE4 or FI once the first price baseline exists.

Define residual load consistently as load minus onshore wind, offshore wind and solar. Handle behind-the-meter PV consistently with the load and generation definitions to avoid double subtraction. A point calculation is a useful first product. Its uncertainty needs joint cross-variable scenarios: subtracting marginal quantiles does not produce residual-load quantiles. The existing temporal copula/shuffle code is a starting point, not a validated cross-variable or cross-zone dependence model.

### Expand by demonstrated capability

After DE-LU, choose FI or a Swedish control zone for transfer testing and a Nordic price case, then a continental market such as France. Rank the next zone by target quality, vintage availability, fleet data and relevance to adjacent prices, rather than making an arbitrary geographic sweep.

Europe-wide prices need cross-border constraints, neighbouring fundamentals and differing hydro/thermal/storage regimes. Start with transparent zonal statistical models and neighbour features; consider a hybrid merit-order/network model only if residual analysis justifies it. Do not infer that accurate local residual load is sufficient for accurate local prices.

Use one zone registry for identifiers, timezone, market interval, weather coverage, capacity definition and target availability. Present separate statuses for public-data coverage, research model, validated model and operational publication. Avoid a Europe map implying custom forecasts exist everywhere.

The current architecture can remain one repository with a forecasting package, acquisition adapters, evaluation and publishing entrypoints. Keep Parquet for research datasets/artifacts and PostgreSQL for operational data that benefits from queries. A public website can read exported results from either. Consolidate duplicated source semantics gradually; moving everything to one storage system is not a prerequisite.

## Ordered delivery plan

These are scope/time-box suggestions for a personal project, not calendar commitments.

| Order | Work | Exit criterion |
|---|---|---|
| P0 — next work session | Diagnose 404; select hosting using the time-box above; publish the thin forecast/performance demo; repair setup docs | A clean-browser visitor can see the actual forecasting work, with accurate dates/status, even when ingestion is unavailable |
| P1 — begin immediately in parallel | Schedule wind/solar publication and pre-cutoff public forecast capture; preserve late/missing runs; start the live scorecard | First on-time immutable forecasts and daily actual-vs-forecast updates; work toward the existing approximately 30-run gate |
| P1 — next modelling milestone | Lock the corrected renewable candidate, evaluate its holdout once, and establish DE-LU price protocol plus naive/LEAR/GBM references | A reproducible current evaluation and an honest first price forecast; vintage gaps explicit |
| P2 | DE-LU custom load/wind, improved solar fleet, residual-load product, public-input versus custom-input price ablation | One complete market and measured downstream value; no requirement that every custom input wins |
| P3 | One transfer market; a bounded DNN/foundation-model comparison; one offline decision study | Evidence of generalisation and a concrete use for the forecasts |
| Later | More bidding zones, shared/global models, scenario dependence, network-aware pricing | Each addition earns coverage through the same validation and operational criteria |

Continue only one major modelling question at a time. Native quarter-hour wind, spatial CNNs and new calibration variants compete with finishing price forecasting; they should not all run as independent roadmap tracks.

## Scope decisions

| Component | Direction |
|---|---|
| Forecast models, data provenance and benchmarks | Invest most development effort here |
| Website | Prioritise immediately, then maintain as the presentation of results |
| CLI | Retain a small set of reproducible fetch/train/evaluate/predict/publish commands |
| Prefect | Reuse if it simplifies operating the existing server; do not extend orchestration as a portfolio objective |
| Market dashboard | Keep charts that explain forecast performance and price drivers |
| LLM integration | Later, explain a selected forecast using structured outputs and measured uncertainty; support evidence links and abstention |
| Generic chat, report formats, alerts, scenario UI | Defer unless needed for the selected forecasting story |
| Multi-tenancy, billing, real-time execution, VPP/asset control | Outside the current portfolio scope |

For the stated employer audience, a successful release should make four things immediately assessable: **what was forecast, what was knowable at issue time, how much skill it added over credible alternatives, and whether it arrived reliably**.
