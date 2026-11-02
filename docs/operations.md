# Local forecast operations

One installed `grid_signals.forecast` package and `grid-signals` CLI own forecasting.
The SE3 saved-model lifecycle and three-service deployment are locally verified.
The owner will deploy manually; server activation, scheduler cutover and current
public forecasts remain pending. Existing local timers continue on preserved 2a
source until that cutover. No remote service was changed for 2b.

For exact model inputs, feature definitions, architectures, selection reasons and
backtest evidence, read the [serving-model guide](../research/docs/dataflow.md).
It includes all SE3 schedules and explains the German manual-command prerequisites;
this operations guide owns the concrete deployment and recovery steps.

Run `uv run grid-signals ui` and open http://localhost:8501. The website reads
portable JSON/Parquet bundles independently of training. Atomic exports keep the last
results available during a production failure, with underlying forecast dates intact.

## Preservation and source consolidation — 2026-11-01

The pre-migration revision is `23986cfa73f93796e74882ce12c86a85f2f62790`.
Local preservation copies are outside this checkout at
`/home/kaarel/Projects/grid-signals-preserved/2026-11-01-before-2a/`:

- `history.bundle`: complete Git history and branch references; verified with
  `git bundle verify`. SHA-256:
  `3c14bcda93974949ce40a9e600ee01b246f669097a0de9727285f739712852e8`.
- `workspace.tar`: original source, datasets, raw provider responses, evaluation
  outputs, publication history, MLflow data and exercises. SHA-256:
  `0972d26eb1b16741cc276af7a110301c7923bfcb61c3b7abb4a70c784c6a3708`.
- `original/`: restored archive; 6,409 research, data, source and notebook files
  were checked byte for byte against the originals before any code moved.
- `systemd/`: copies of the six original service/timer unit files, saved before
  updating service commands to the installed CLI.
- `SHA256SUMS`: archive checksums. Environment/credential files, tool settings,
  virtualenvs and caches are excluded; this is a local preservation copy.

The standalone notebooks were also copied and checked in
`/home/kaarel/Projects/grid-signals-learning/notebooks/`. Local research data and
original frozen model version records remain in place. No containers, database
services or Docker volumes were removed; the local running-container inventory
contained no Grid Signals market database. Remote services were not changed.
Older market deployment/recovery instructions remain recoverable from the Git
bundle and original snapshot; do not delete old remote volumes or backups based
on removal of their application code.

Local cleanup on 2026-11-02 removed the unused empty `deploy/demo`, `deploy`,
`research/src` and `research/notebooks` directories, plus the retired `briefings`
directory. Its only file, `2026-03-26.md`, matched the preserved copy under
`original/briefings/` byte for byte before removal.

For exact original evaluation reproduction, work in a separate restored directory,
install its original locked environment, and use its original `research/src`
imports and cached inputs. Do not rewrite old source paths or checksums to point
at moved files. The consolidated package has a separate code version record at
`src/grid_signals/forecast/configs/releases/consolidated_v1.json`. The 2a publications
verify that record and use its identity. It links the historical records and load
selection by checksum without claiming a new final evaluation. A new code/settings
revision requires a new record, created with `grid-signals version --register PATH`
and selected through `GRID_SIGNALS_VERSION_RECORD`; this is code identity, not the
saved-trained-model promotion. The 2b runtime has a separate record described below;
the original and 2a records remain unchanged.

Migration checks compare original and moved models on deterministic wind, solar,
load and price inputs, including quantile predictions and scores. Model, feature,
target and evaluation syntax trees agree after import renaming. Fresh exports from
the preserved and installed code have identical 13 Parquet files and zone inventory;
all three summary bundles agree except generation timestamps. The existing
bundled results and historical records have not been regenerated. Unindexed local demo
exports were moved to `data/retired_demo_exports` so package builds include only
the current result files.

Configuration is shared by local and scheduled operations. Set
`GRID_SIGNALS_DATA_DIR` and `GRID_SIGNALS_OUTPUT_DIR` to absolute paths for mounted
volumes. Optional settings/report/tracking roots and CLI examples are in the
[README](../README.md#forecast-commands-and-configuration). To preview new exports,
set `GRID_SIGNALS_EXPLORER_PATH` to the exported `explorer` directory and
`GRID_SIGNALS_SNAPSHOT_PATH`, `GRID_SIGNALS_PRICE_SNAPSHOT_PATH` and
`GRID_SIGNALS_LOAD_SNAPSHOT_PATH` to the three exported summary files.

## Daily local trial

The old local trial remains the active schedule until the owner's Prefect cutover.
The installer and shell wrapper have been retired from this checkout. The three
existing user services use the checked source from commit
`20b607b` in
`/home/kaarel/Projects/grid-signals-preserved/2026-11-01-before-2b/source`,
selected by their `PYTHONPATH` environment setting. Copies of the unit files are
in that preservation directory's `systemd/` folder. The preserved package's code
record verifies. Data locations, timers and their schedules were not changed;
systemd was reloaded without starting jobs. Do not add another active scheduler
for these issues before the cutover.

Inspect with `systemctl --user list-timers 'grid-signals-*'`. The old schedule remains:

| Job | UTC | Behaviour |
|---|---|---|
| Save public forecasts | 08:55 | Preserve ENTSO-E wind/solar and load forecasts with raw metadata |
| Forecast | 09:00 | Refresh inputs; independently publish wind, solar, price and load; export snapshots |
| Score | 15:00 | Refresh actuals, score eligible first publications, update snapshots |

Deadline: 09:30 UTC. Missed timers run on resumption with their actual late or
retrospective status. Jobs have a 27-minute timeout and four-worker limits.
This is a local user-session schedule: the machine needs to be running, online
and able to execute user services. It is not an always-on server deployment.

Root `.env` supplies ENTSOE_API_KEY. No database or LLM key is needed. Failure
records store exception types, not credential-bearing HTTP URLs.

```bash
journalctl --user -u grid-signals-forecast.service --since today
journalctl --user -u grid-signals-capture.service --since today
journalctl --user -u grid-signals-score.service --since today
```

Evidence is under `research/data/operational/`: trial start, unchanged job records and saved public forecasts, raw XML/Parquet and renewable/price scorecards. Forecast Parquet archives
are under `research/data/predictions/`. Only first on-time issues are scored;
retries do not replace them. Scores await complete actual delivery days and remain
provisional as actuals change. The first scheduled trial issue is October 16;
today's late forecasts contribute no on-time evidence. Historical replay cannot
satisfy the 30-run integration gate.

Price publication now uses the declared LEAR baseline in
`src/grid_signals/forecast/configs/price_forward.yaml`, with hourly distributions repeated onto market
quarter-hours. Historical direct-quantile price forecasts remain archived as a
separate model version. Load is published with the candidate selected before its
final evaluation. Each product has its own forward scorecard.

Exact reproduction of the frozen load release requires its original local input
matrix. The model version record stores its checksum; newer API observations can contain revisions
and must not silently replace that matrix. The price-input experiment also requires
the original price cache. Portable website bundles include results, not training data.

Disable the schedule with:

```bash
systemctl --user disable --now grid-signals-capture.timer grid-signals-forecast.timer grid-signals-score.timer
```

## SE3 producer deployment — milestone 2b

Implementation is ready for manual deployment from `feat/electricity-forecasting`.
`compose.forecast.yaml` runs one Prefect server, one runner and one web service.
This replaces the multi-product local schedule with **SE3 onshore wind only**;
German results remain historical case studies and manual commands. The historical
public site stays available during setup.

### What is implemented

- `forecast_runtime_v2.json` identifies runtime
  `forecast-runtime-v2+1a775e36653d5d5b`. The daily saved-model policy is
  `se3-wind-saved-v1-daily-before-issue`, a new forward version. Each preparation
  retains exact training inputs, lag history, settings, code/dependency identities,
  training cutoff, trained model, fitted physical reference and a reload comparison.
  It excludes training delivery days at or after the preparation/issue cutoff.
- Preparation validates and explicitly promotes a saved model. Prediction only
  loads the matching issue's promoted model. Changed files, code or dependencies,
  models prepared after the issue cutoff and models over 30 hours old are rejected.
  Train inside the deployed runner: the local Python 3.13 validation artifact is
  intentionally incompatible with the runner's pinned Python 3.12 environment.
- Durable candidate files precede publication. All public payloads are checked
  before a whole-generation pointer is committed. A delivery receipt is confirmed
  only after that generation is readable. A crash before confirmation remains
  unverified; recovery uses its real confirmation time. Retries preserve confirmed
  first publications. The web pins a checked generation and can fall back to the
  previous one or bundled history, with a warning.
- Publication pages expose every due day, missing/late/failed issues, freshness,
  model and collection evidence. The client derives missing due days even when
  the producer stops; a snapshot older than 45 minutes is visibly stale.
  Forward scores use complete actual days and the first verified on-time receipt,
  matched against the saved physical reference. Public point forecasts are compared
  only with complete, hashed responses received before the information cutoff.
  Bias, CRPS and interval coverage are retained; scores remain revisable with actuals.
- Provider phases have separate status, error type and elapsed time. Actuals and
  weather fetching have bounded retries/timeouts; fitting and prediction do not
  retry blindly. Historical `ReadTimeout` records do not identify the original
  provider/root cause. The new controls and visibility are tested, but live
  evidence that those failures are resolved is still required.

All six deployments use UTC and share a single runner slot and data lock:

| Operation | UTC schedule | Behaviour |
|---|---|---|
| Backup | 03:00 | Checked data/results and online SQLite backup |
| Prepare | 06:00 | Refresh inputs, fit, verify reload, promote for today's issue |
| Capture | 08:55 | Save the public SE3 wind forecast before the cutoff |
| Forecast | 09:00 | Fetch eligible weather, load saved model, deliver by 09:30 |
| Score | 15:00 | Refresh actuals and publish matched scores |
| Status | Every 15 minutes | Publish current due-day and job status |

Prefect schedules keep their original scheduled day across restarts. Overdue
forecast/preparation/collection runs fail visibly instead of using newer inputs
to fabricate on-time evidence. Local commands call the same flow/task functions.
The static runner uses Prefect's [local-process deployments](https://docs.prefect.io/v3/how-to-guides/deployment_infra/run-flows-in-local-processes).
Schedules start **paused**; the server persists its SQLite database independently
of runner and page serving.

### Manual deployment steps

1. Make the reviewed commit available on `feat/electricity-forecasting` when ready
   and wait for its CI checks. No push or remote deployment was performed during
   preparation. Leave Dokploy automatic deployment disabled.
2. In Dokploy, create a **Docker Compose** application from this repository and
   branch, using `compose.forecast.yaml`. Build from the repository root. Set:

   ```dotenv
   ENTSOE_API_KEY=your-existing-provider-key
   GRID_SIGNALS_IMAGE_TAG=the-reviewed-commit
   GRID_SIGNALS_SCHEDULES_PAUSED=true
   GRID_SIGNALS_RUNNER_MEMORY=3g
   GRID_SIGNALS_RUNNER_CPUS=2
   ```

   The image tag is a label: deploy the reviewed source commit as well. The runner
   alone receives the provider key. Four named volumes persist forecast data,
   public results, Prefect state and backups. The web mounts results read-only.
   All app processes run as UID 10001. Default memory caps total 4.75 GiB; ensure
   the host also has room for Dokploy, builds and existing services. Host capacity
   has not been checked. Do not remove these volumes when updating containers.
3. Deploy with schedules paused. Check that `prefect` and `runner` are healthy and
   `web` serves `/_stcore/health`. On the host the diagnostic endpoints are bound
   to loopback: Prefect `http://127.0.0.1:4200` and web
   `http://127.0.0.1:8503`. An SSH tunnel can reach them without publishing Prefect.
   Confirm the six `se3-*` deployments are paused. The runner health server uses
   internal port 8080. Dokploy's [Compose guide](https://docs.dokploy.com/docs/core/docker-compose)
   describes its application setup.
4. Transfer the checked seed archive from this workstation:
   `data/deployment/se3-seed-2026-11-01.tar.gz` (identity recorded below). Upload it
   to the server using your normal file transfer. Find the runner's actual
   container name in Dokploy and replace `RUNNER_CONTAINER` below:

   ```bash
   docker cp /path/on/server/se3-seed-2026-11-01.tar.gz RUNNER_CONTAINER:/tmp/forecast-seed.tar.gz
   docker exec --user 10001 RUNNER_CONTAINER python -m grid_signals seed /tmp/forecast-seed.tar.gz
   ```

   `seed` verifies every archived file, imports inputs/history/tracking into an
   **empty** data volume and records the archive checksum. It refuses an existing
   producer's data. It does not activate the trial or promote the local validation
   model. Keep the original checked archive outside the server as a recovery source.
5. Choose a future first issue day, usually tomorrow, and replace `YYYY-MM-DD`.
   Prepare and validate before its 09:00 UTC cutoff:

   ```bash
   docker exec --user 10001 RUNNER_CONTAINER python -m grid_signals activate --first-issue-day YYYY-MM-DD
   docker exec --user 10001 RUNNER_CONTAINER python -m grid_signals workflow prepare --issue-day YYYY-MM-DD
   docker exec --user 10001 RUNNER_CONTAINER python -m grid_signals workflow status --issue-day YYYY-MM-DD
   ```

   `activate` does not reset an existing trial. Preparation fetches current data,
   fits inside the deployed environment and promotes only after validation. Its
   output names the model; the public status details must show `active_model`
   ready, a pre-issue preparation time and a training end before the cutoff.
   If setup misses the cutoff, use the next issue day; do not backdate it.
6. Add a temporary preview domain to the Compose **web** service, internal port
   **8501**, with HTTPS. Use Dokploy's [Compose domain settings](https://docs.dokploy.com/docs/core/docker-compose/domains).
   Check the historical pages, the new Daily SE3 wind section on Overview and
   Performance, CSV downloads and phone navigation. The first issue is pending
   until the actual scheduled forecast arrives. Keep the existing historical
   demo/image available for rollback; move the test domain to this web service
   after the preview checks pass. The final domain and `main` merge remain deferred.
7. Before unpausing the server, run this **on the original workstation**:

   ```bash
   systemctl --user disable --now grid-signals-capture.timer grid-signals-forecast.timer grid-signals-score.timer
   systemctl --user list-timers 'grid-signals-*'
   ```

   Then set `GRID_SIGNALS_SCHEDULES_PAUSED=false` in Dokploy and redeploy the runner
   with the same volumes and reviewed image. Confirm all six schedules are active.
   Do not run both schedulers. The first preparation at 06:00 may replace the
   checked bootstrap model under the same declared daily policy.
8. After 09:00–09:30 UTC on the first issue day, check a current forecast through
   the anonymous HTTPS site and download its CSV. Verify its delivery date,
   saved model/training cutoff and actual publication time. Check collection and
   any failure records, then complete actuals/scores on subsequent days. Record
   the deployed commit/image, domain, first issue and backup destination here.
   Server restart, off-host recovery and the approximately 30 consecutive on-time
   issue gate require deployment evidence before claiming dependable operation.

### Backup and recovery

The initial transfer archive is
`data/deployment/se3-seed-2026-11-01.tar.gz`, with 6,144 checked files and SHA-256
`28e3f6c0d94745c9600e1235b734c925f9eb2aa2d25af9dd8773ec087f90ff1a`.
It includes local inputs, historical evidence, tracking and the unpromoted model
validation artifact. It contains no deployed Prefect database and does not reset
or import an active new-producer trial. The archive is gitignored and must be
transferred separately from the source commit. Restoring this exact archive into
a separate temporary directory verified all 6,144 files before handoff.

The 03:00 job saves `/backups/forecast-<UTC time>.tar.gz`, including recorded
inputs, saved models, publication evidence, results, experiment metadata and an
online checked copy of Prefect's SQLite database. Manual equivalents:

```bash
docker exec --user 10001 RUNNER_CONTAINER python -m grid_signals backup /backups/manual-check.tar.gz
docker exec --user 10001 RUNNER_CONTAINER python -m grid_signals restore /backups/manual-check.tar.gz /backups/restored-check
```

Restore requires a new destination and checks its complete file index and
checksums. This command verifies an archive; it does not overwrite running
volumes. For a real recovery, pause/stop runner and server, restore into new
volumes, place restored `data/`, `public/` and `prefect.db` at their respective
mount roots with UID 10001 ownership, and start the same reviewed images with
schedules paused. Retain old volumes until checks pass. Validate the promoted
model in that exact environment, inspect the last public receipt and six Prefect
deployments, then resume. Newer code/environment must not silently reuse an
incompatible model. Never turn a recovered late issue into an on-time receipt.

The named backup volume is on the same host. Copy checked archives to a separate
host/storage location and set retention appropriate to available space; no
off-host destination or automatic cleanup is configured. Do not delete original
evaluated inputs, frozen code/model records or first-publication evidence.
Dokploy also provides [volume backups](https://docs.dokploy.com/docs/core/volume-backups);
application backups use SQLite's online backup API for a consistent database copy.

### Local verification — 2026-11-01

- 315 tests passed, 2 skipped. Checks include the real temporary Prefect engine,
  fixed-input fitted-versus-reloaded predictions, crossfit calibration, 92/96/100
  interval delivery grids, incomplete actuals, bad/missing model files, deadline
  crossing, delivery interruption/retry and verified backup/restore/seed behaviour.
- Ruff lint/formatting passed. Both final images passed checks without network
  access or credentials. The runner check performs synthetic preparation,
  promotion, prediction, publication and recovery as UID 10001; web/experiment
  dependencies are excluded from the runner.
- An isolated Compose stack started healthy, registered six paused UTC schedules,
  retained all six IDs and pause states across server/runner restarts, and restored
  its real Prefect database with six deployment rows. The web result mount was
  verified read-only. No real provider calls or scheduled forecasts were run.
- Desktop (1440 px) and phone (390 px) browser checks passed for the new publication
  record, latest forecast navigation and both CSV downloads. Forecast CSVs included
  96 intervals and saved-model/training metadata. This used isolated synthetic
  results; it did not publish new live evidence. No browser errors or page overflow
  were found.
- A cached-data preparation with the default crossfit settings used 934 training
  days / 22,392 hourly rows, took 249.1 seconds and peaked at 1,075.6 MiB RSS.
  Loading that model and predicting a fixed 96-hour input took 1.4937 seconds;
  predictions agreed within `1e-12`. This uncapped workstation measurement excludes
  provider fetching and feature construction and is not a host/deadline guarantee.
  The retrospective 2026-10-22 artifact and verification are retained under
  `research/data/model_validation/`, unpromoted and unscored. It is not a serving
  model for the runner's different Python environment.

The actual host, domain cutover, first current issue/scores, off-host recovery and
ongoing reliability checks remain the owner's manual deployment work.

## Refresh the historical explorer

The website has one shared market/date/target/model selection, full backtest
series and grouped diagnostics. Exporting reads **completed** research evaluations;
it never trains or reopens a sealed holdout:

```bash
uv run grid-signals export explorer --historical
```

Daily delivery commits complete generations separately. Historical flat exporters
name files using checksums and update the file index (`manifest.json`) last.
Old generations can be removed when no running reader needs them. The web image
contains the exported result files, not the raw cache.

Generated Parquet exports are ignored by Git; the files already committed remain
tracked. Exports default to `data/exports`; use
`uv run grid-signals --output-dir src/grid_signals/app/assets export all --historical` only
when deliberately refreshing bundled results. When updating the bundled demo, commit the updated file index together
with its referenced result files. Use `git add -f` for newly generated files listed
in that index, rather than adding every older export in the directory.

Additional market observations are a bounded preview, separate from forecast inputs:

```bash
uv run grid-signals fetch-context --start 2026-09-01 --end 2026-10-16
```

Use `--refresh` to replace this preview with a different range (maximum 90 days),
then export again. ENTSOE_API_KEY is read from the root .env. Current areas: DE-LU,
SE1–SE4, FI, EE, FR, NL, DK1 and DK2. Only DE-LU and SE3 have custom forecasts;
missing offshore observations prevent residual-load derivation. Historical charts
and metrics preserve source resolution, daylight eligibility and DST interval order.

[Volue examples](https://docs.volue.com/data-and-forecasts/volue-insight-timeseries/guides/examples)
informed the aligned fundamentals and forecast/actual comparison. The map uses
[entsoe-py bidding-zone geometry](https://github.com/EnergieID/entsoe-py/tree/master/entsoe/geo),
simplified for display. The local `market-areas.geojson` records the source package
version, per-file checksums and MIT license. Ireland/Northern Ireland use the
prior local Natural Earth outlines (public domain). Geometry is display context
rather than an operational boundary definition. The map includes all 39 areas in
the project's [SDAC registry](https://www.entsoe.eu/network_codes/cacm/implementation/sdac/).

## Public hosting

The owner confirmed the Dokploy test deployment on **2026-11-01**:
[grid-signals-demotest.kaarelkivisalu.ee](https://grid-signals-demotest.kaarelkivisalu.ee).
It is deployed from `feat/electricity-forecasting`. Anonymous requests to the
homepage and `/_stcore/health` returned HTTP 200 with certificate verification
enabled; the health response was `ok`. Public acceptance checks passed on
2026-11-01 (details below). The owner supplied the deployed commit and Docker
build output for this deployment:

| Item | Recorded value |
|---|---|
| Git commit | `5e08069c9a9fdcc62598da1ede6fba4ad2458cbf` |
| Image tag | `docker.io/library/gridsignals-gridsignalsdemo-95atzm:latest` |
| Image index (manifest list) digest | `sha256:99fa7561577e72e40a0c6a6b22e75b029b0a3a3415690dcdce05286d78fba8d1` |
| Image manifest digest | `sha256:ad8a033f5e0a397afa5aefcad7a10f54b541689f38c8a62200bd7400b0e1a54c` |
| Image config digest | `sha256:3578c823e81a7e84e89912d15d9112c8e558b5428d9856b22ded1a3404371ad2` |

These digests identify the build output; the `latest` tag can change on a later
build. The local image name does not establish that the image was pushed to a
registry.

Keep this test domain while developing the roadmap. Once the roadmap is
reasonably complete and the owner approves merging into `main`, change the
deployment source to `main` and the domain to
**`https://grid-signals.kaarelkivisalu.ee`**, configure its DNS and HTTPS, and
repeat the public acceptance checks. The final domain is planned, not verified.

The presentation has a separate, non-root web-only image with pinned UI dependencies.
Start it locally with Docker Compose:

```bash
docker compose -f compose.demo.yaml up --build -d
```

Open http://localhost:8502. The image includes the historical explorer and three summary bundles and omits the
legacy database/agent tools. Its build context excludes research data, secrets and
the virtualenv. The build checks every indexed Parquet file's checksum and copies
only those files into the final image. Older local exports are preserved under
`data/retired_demo_exports`, outside installed package assets.
View logs with `docker compose -f compose.demo.yaml logs -f`; stop and remove the
demo container with `docker compose -f compose.demo.yaml down`.
Use `compose.demo.yaml` explicitly. The original market Compose files and worker
Dockerfile were removed in 2a; use `compose.forecast.yaml` for the new producer.
The Python runtime and uv builder images are pinned by digest. The Dockerfile
follows Astral's [multistage example](https://github.com/astral-sh/uv-docker-example/blob/main/multistage.Dockerfile):
the uv 0.13.6 Python builder runs `uv sync --locked` with a shared build cache and
compiled bytecode, then prepares the checked website files. The final Python
image copies those files and `/app/.venv`; it contains no uv binary or build cache.
The website runs directly with the virtual environment's Python as UID 10001.
The root `pyproject.toml` defines `web`, `runner`, `research` and `dev` groups;
root `uv.lock` locks all profiles. The image installs only base/web dependencies
with `uv sync --locked --no-default-groups --group web --no-install-project`.
There is no separate demo project or lockfile. Update dependencies deliberately
with `uv lock`, then rerun release checks.

Check the built image without networking or credentials:

```bash
docker run --rm -i --network none --entrypoint python grid-signals-demo:local < tests/demo_image_check.py
```

The same build and offline check run in CI. Refresh result bundles only when
intentionally publishing newer results, then rebuild. No refresh or training is
needed to deploy the saved historical release.

### Historical release and local review

Overview opens on **SE3, 2026-09-19** with a price graph and a combined fundamentals
graph. Area and date controls are visible. The saved selected model supplies at
most one forecast per product; products without a forecast show observations
only. Price uses EUR/MWh; fundamentals use MW with whole-MW axis labels and
tooltips. Overview omits repeated selection captions and the demand case-study
link; demand has a separate page. The sidebar has three
groups: Overview/Map, Prices/Wind/Solar/Demand, and Models & data/Performance.
Area choices group country zones and nearby single-area markets, with
EE/LV/LT together. Buttons join edge to edge with square corners, small gaps
between groups and no country headings. Unsupported choices are greyed out for
each page.

Product pages use area and date as the main controls, with alternative models
and earlier publications in expandable sections. The selected date determines
whether a forecast is a historical evaluation, development result or published
issue; the page explains that distinction. Chart legends name the forecast and
reference. Forecast/error panels and CSV downloads remain available.
Performance leads with matched scores and monthly error patterns; evaluation
period and model controls are optional. Models & data explains each approach
with a responsive input-to-forecast diagram before its regional applications.
Detailed sources, fitting rules and timing assumptions can be expanded. Product
selectors use joined buttons, matching area selectors. Delivery dates use a 160 px
calendar field joined to
two arrow buttons that move between saved days; missing dates show an explicit
empty state. The clear control is disabled; an empty value sent by an older
browser restores the last selected day before date-range checks. Map keeps all
39 SDAC areas visible in a larger map with plain labels. Its compact table puts
groups with evaluated forecasts first, followed by groups with observations,
then unavailable groups. All rows scroll with the page.
Areas link to Overview, evaluated cells to product
pages, and observation-only cells to Overview. Unavailable cells have no data link.
Forecast shading uses saved quantiles, not ensemble scenarios.

The bundled file index was exported at **2026-10-23T15:00:31.076936+00:00** and
references 13 checked, Git-tracked Parquet files. SE3's final evaluation covers
2026-03-20 through 2026-09-19, with 182 of 184 complete days. Later issues retain
their recorded publication times and statuses. The export date does not imply
current forecasts or reliable daily updates. Original evaluated results, model
version records and their source files are unchanged.

The 2026-10-26 portfolio checks passed: **407 tests, 2 skipped** before the latest
UI revisions. The calendar and layout revision passed **47 focused tests**, Ruff lint and
formatting, two offline image checks and desktop/tablet/phone browser review at
1440, 820 and 390 px. Navigation and CSV downloads work without browser errors,
external requests or horizontal page overflow. Tests cover grouped choices,
one forecast per product, observation-only areas, all map links, the full zone
table, calendar navigation across missing days, cleared-date recovery on Overview
and Wind, preserved selections and aligned error values. The publication-status
test checks the selected issue.
Existing evaluated result files and model code were not changed.

The 2026-11-01 usability revision passed **52 focused tests**, Ruff lint and
formatting, and local browser checks at 1440, 820 and 390 px. Forecasts select
the saved result type by date, chart references are named, and model guides work
independently of area selection. Navigation, CSV downloads and responsive diagrams
passed without browser errors or horizontal page overflow. This review used a
separate local Streamlit preview; the running Docker demo was not refreshed.

The deployed test site passed anonymous Chromium acceptance checks on
**2026-11-01** at **1440 × 1100** and **390 × 844**. Overview, Wind, Solar,
Prices, Demand, Performance, Models & data and Map rendered without application
exceptions, browser errors or horizontal page overflow. Phone sidebar navigation,
previous/next saved-day controls and the forecast-to-methods link worked. Wind
opens on SE3's populated historical comparison; German solar, price and demand
case studies remain accessible. Forecast pages explicitly label the selected
2026-09-19 results as historical evaluation. On both screen sizes, each of the
four forecast CSV downloads contained 96 quarter-hour intervals for that delivery
date, with actuals and median forecasts. Desktop performance and phone wind
screenshots were also reviewed. These checks complete historical-demo acceptance;
they do not establish daily production or freshness. The deployed Git revision
and image identity are recorded above.

Standalone learning notebooks have moved out in milestone 2a. Three style rules
remain narrowly exempted in the moved split/conformal modules to avoid incidental
algorithm edits during consolidation; original evaluated source is preserved separately.

### Manual deployment steps for the owner

The test site is deployed and anonymous HTTPS access is verified. Use these
steps for later demo updates or to recreate the web service:

Deploy from **`feat/electricity-forecasting`** while the roadmap is being developed.
Keep this branch name stable. Updating `main` is a separate owner decision once
the roadmap is reasonably complete; deployment needs no pull request or merge.
GitHub Actions runs lint, tests and the offline demo-image check on each push to
this branch. Leave Dokploy automatic deployment disabled and deploy manually
after the checks pass for the commit being deployed.

1. Review the local demo at http://localhost:8502, then make the reviewed Git
   revision available with `git push -u origin feat/electricity-forecasting` when
   ready. Wait for that commit's GitHub Actions checks to pass. Local preparation
   does not push code.
2. Choose a **Dockerfile** build with the repository root as context and
   **`Dockerfile.demo`** as the Dockerfile. Set the source branch to
   **`feat/electricity-forecasting`** and deploy the reviewed Git revision.
3. Set the internal port to **8501**, leaving the startup command and health check
   in place. No API keys, database settings or persistent volumes are needed.
   The image runs as UID 10001; its health endpoint is `/_stcore/health`.
4. Add the chosen domain and enable HTTPS in Dokploy, routing to container port
   8501. Port 8502 is only the local preview port.
5. Use a signed-out browser to check HTTPS, the historical SE3 date and chart,
   all product and evidence pages, German case studies, CSV downloads and phone navigation.
6. Record the public URL, Git revision, image identity and deployment date in this
   guide. Repeat the public checks after each deployment. Keep the previous image
   available for rollback when updating the demo.

The initial historical release needs only the web service. The target daily
deployment adds a Prefect server and forecast runner on the same host, with
persistent product data and a published-results volume mounted read-only in the
web container. See the [target deployment](implementation-plan.md#how-the-deployed-system-should-run).
`compose.forecast.yaml` implements that target; follow the separate
[producer deployment steps](#se3-producer-deployment--milestone-2b), including data
seeding and scheduler cutover. The demo-only steps above do not activate daily forecasts.

Existing Dokploy capacity hosts the test site; reconsider hosting only for a
concrete operational or cost constraint. The
[roadmap](../ROADMAP.md) defines release acceptance; the
[historical direction review](project-direction-review.md) retains the comparison.
