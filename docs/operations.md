# Forecast operations

Start with the task you need:

- [Configure paths and dependencies](#configure-paths-and-dependencies)
- [Prepare and run an issue locally](#prepare-and-run-an-issue-locally)
- [Run development comparisons](#run-development-comparisons)
- [Deploy the SE3 producer](#se3-producer-deployment--milestone-2b)
- [Monitor runs and inspect files](#monitor-runs-and-inspect-files)
- [Back up and restore](#backup-and-recovery)
- [Refresh website results](#refresh-the-historical-explorer)
- [Update the historical site](#public-hosting)
- [Inspect or stop the old workstation timers](#daily-local-trial)

The [roadmap](../ROADMAP.md) owns deployment status and acceptance. Publication
eligibility follows the [publication contract](integration_contract.md).

## Configure paths and dependencies

Use `uv sync --frozen --group research` for full development. Minimal environments:

```bash
uv sync --frozen --no-default-groups --group web
# Or, for the producer:
uv sync --frozen --no-default-groups --group runner
```

One lockfile covers all groups; MLflow and plotting belong to experimentation.
Set paths before importing pipelines. CLI root options go before the command.

| Environment variable | CLI option | Default relative to the working directory |
|---|---|---|
| `GRID_SIGNALS_DATA_DIR` | `--data-dir` | `research/data` |
| `GRID_SIGNALS_OUTPUT_DIR` | `--output-dir` | `data/exports` |
| `GRID_SIGNALS_CONFIG_DIR` | `--config-dir` | Packaged `src/grid_signals/forecast/configs` |
| `GRID_SIGNALS_REPORTS_DIR` | `--reports-dir` | `research/reports` |
| `GRID_SIGNALS_MLRUNS_DIR` | `--mlruns-dir` | `research/mlruns` |

Use absolute paths with mounted volumes or outside the checkout. The web reads
`GRID_SIGNALS_RESULT_ROOT` for checked daily generations. For flat historical
exports, `GRID_SIGNALS_EXPLORER_PATH` selects the explorer directory;
`GRID_SIGNALS_SNAPSHOT_PATH`, `GRID_SIGNALS_PRICE_SNAPSHOT_PATH` and
`GRID_SIGNALS_LOAD_SNAPSHOT_PATH` select the three summary files.

## Prepare and run an issue locally

Requires `ENTSOE_API_KEY` in the root `.env`, historical input caches and the
[bootstrap data](#backup-and-recovery). The following commands fetch data and
write model/publication state. Use isolated data/output roots for experiments;
run scheduled issues through their existing schedule owner.

For a new isolated trial, first run
`uv run grid-signals activate --first-issue-day YYYY-MM-DD` with a future issue
day. This records the first due issue and does not reset an existing trial.
Replace `YYYY-MM-DD` below and prepare before that issue day's 09:00 UTC cutoff:

```bash
uv run grid-signals info
uv run grid-signals workflow prepare --issue-day YYYY-MM-DD
uv run grid-signals workflow status --issue-day YYYY-MM-DD
```

Preparation fetches data, fits, verifies reload and promotes under the daily
policy. Status must show a ready `active_model` and a training end before cutoff.
At 08:55 UTC, collect the public comparison:

```bash
uv run grid-signals workflow capture --issue-day YYYY-MM-DD
```

At 09:00 UTC, generate and deliver the forecast:

```bash
uv run grid-signals workflow forecast --issue-day YYYY-MM-DD
```

After complete actual delivery days are available, update scores and results:

```bash
uv run grid-signals workflow score --issue-day YYYY-MM-DD
uv run grid-signals export all
```

Capture must finish before the 09:00 UTC cutoff; forecast delivery is due by
09:30 UTC. Scores for an issue await its next-day delivery actuals. Manual
commands retain real timestamps: replay cannot become on-time evidence. SE3
prediction loads the matching promoted model; it does not fit. Use `--no-refresh`
with `workflow forecast` only when the required weather is already cached.

For lower-level model control, use `model prepare`, `model validate` and
`model promote`; inspect `--help` before changing promotion policy. German
case studies use manual `forecast --product de-solar`, `de-load` or `de-price`
with their own cached inputs and fitting path; they have no new Prefect schedules.
See the [model guide](dataflow.md) for prerequisites.

## Run development comparisons

Requires the full research environment, the selected product's cached inputs and
provider credentials when fetching data. These commands write development
results; they do not reopen frozen final evaluations:

```bash
uv run grid-signals fetch-actuals 2026-10-01 2026-10-15
uv run grid-signals fetch-price 2026-10-01 2026-10-15
uv run grid-signals fetch-load 2026-10-01 2026-10-15
uv run grid-signals refresh-weather --help
uv run grid-signals train --help
uv run grid-signals backtest --fuel wind_onshore
uv run grid-signals backtest --fuel solar
uv run grid-signals backtest-price
uv run grid-signals backtest-load
uv run grid-signals experiment decision_study
```

Select dates for the intended development study. `train` fits/scores the existing
development comparison; `backtest` runs the quarter-hour product comparison.
Other experiment names and options are listed by `grid-signals experiment --help`.
The decision example shifts 1 MWh/day into eight quarter-hours under a 0.5 MW limit.
It uses development predictions, allows interruptions and excludes fees, taxes
and grid charges. Weekly persistence captures most benefit versus uniform
consumption; this is not a trading-profit claim.

Inspect `uv run grid-signals version` for code identity. Changed code/settings
requires a new record using `version --register PATH` and selection through
`GRID_SIGNALS_VERSION_RECORD`. This differs from saved-model promotion; never
rewrite frozen records. See [research reproduction](../research/README.md#reproduce-or-extend-the-work).

## SE3 producer deployment — milestone 2b

Implementation is ready for manual deployment from `feat/electricity-forecasting`.
`compose.forecast.yaml` runs one Prefect server, one runner and one web service.
This replaces the multi-product local schedule with **SE3 onshore wind only**;
German results remain historical case studies and manual commands. The historical
public site stays available during setup.

Train models inside the deployed runner: the local Python 3.13 validation artifact
is incompatible with the runner's pinned Python 3.12 environment. Prediction rejects
incompatible, stale, changed or post-cutoff models. Read the
[model preparation rules](dataflow.md#33-architecture-training-and-promotion)
and [delivery contract](integration_contract.md) before changing that policy.
Schedules default to paused; enable them only after disabling the old timers.

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

## Refresh the historical explorer

The website has one shared market/date/target/model selection, full backtest
series and grouped diagnostics. Exporting reads **completed** research evaluations;
it never trains or reruns a frozen final evaluation:

```bash
uv run grid-signals export explorer --historical
```

For daily results, `uv run grid-signals export all` commits a checked complete
generation to `data/exports/`. Use a root option such as
`uv run grid-signals --output-dir /absolute/results export all` to select another
destination; preview it with `GRID_SIGNALS_RESULT_ROOT=/absolute/results`.
Exporting does not train models, score holdouts or start a trial.

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

Use `Dockerfile.demo` for the standalone historical site. It needs no credentials
or persistent volumes. For local preview, follow the [quick start](../README.md#run-the-local-demo).
The [deployment record](archive/operations-record.md#public-hosting) retains the
public URL, deployed commit, image digests and acceptance checks. Deployment
source and domain changes follow the [roadmap](../ROADMAP.md).

Before publishing an update, run `bash scripts/check.sh`. Its `demo` group builds
and checks the web image without networking or credentials. Refresh bundled
results only when deliberately publishing new evidence.

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
[historical direction review](archive/project-direction-review.md) retains the comparison.
## Monitor runs and inspect files

Inspect Prefect flow/task failures and the public due-day status. A successful flow
alone does not prove public delivery. Provider-phase records retain error type and
elapsed time without credential-bearing URLs. Check the latest confirmed receipt,
model readiness, weather availability and complete actuals when an issue or score
is missing. Historical `ReadTimeout` records do not identify the original provider;
live evidence is still needed to establish whether the new handling resolves it.


| Under configured data/result roots | Meaning |
|---|---|
| `/data/raw/`, `/data/parsed/`, `/data/interim/` | Provider data, parsed weather and derived targets; exact source-specific paths in `sources/` |
| `/data/models/se3-wind/<model_id>/` | `record.json`, `training.parquet`, `lag_targets.parquet`, `reload_inputs.parquet`, `reload_predictions.npz`, `model.pkl` |
| `/data/models/se3-wind/active.json`, `promotions/` | Checked active-model pointer and immutable promotion reasons/history |
| `/data/runtime/se3-wind/trial.json`, `lifecycle/` | First due issue and per-phase status/error type/elapsed-time records |
| `/data/runtime/se3-wind/issues/<forecast_id>/` | Candidate `inputs.parquet`, `forecast.parquet`, checksummed `record.json` |
| `/data/operational/captures/`, `/data/operational/raw_captures/` | Public comparison collection evidence; `/data/operational/actual_fetches/` holds fresh SE3 observation receipts; see `journal.py` and `sources/capture.py` |
| `/results/generations/<id>/` | Complete checked explorer/summary payloads, `publication.json`, `files.json` |
| `/results/current.json`, `previous.json` | Whole-generation pointers; confirmed delivery receipt and its real timing |
| `/backups/forecast-<UTC timestamp>.tar.gz` | Checked recovery archive; retain/copy off-host explicitly |

Local defaults are `research/data`, `research/mlruns`, `data/exports` and
`research/reports`; environment variables or CLI root options select mounted
locations before imports. See [paths.py](../src/grid_signals/forecast/paths.py).
The saved pickle requires its recorded compatible environment and trusted origin;
checksums identify our own artifact, not arbitrary downloaded models.

Publication implementation is [live.publish/acknowledge/status_record](../src/grid_signals/forecast/live.py).
Only after the complete generation is visible is a receipt confirmed; a crash
before confirmation stays unverified and recovery uses its actual later time.
Retries cannot replace an earlier first eligible receipt. Scores use complete
native actual days and matched intervals, with physical error, bias, CRPS and
coverage; public point MAE is added only with eligible capture evidence. Scores
can change with revised actuals. The web reader
[results.py](../src/grid_signals/app/results.py) verifies payloads, falls back
to previous/bundled data with a warning, derives missing due days during outages,
and flags snapshots older than 45 minutes. Prefect success alone does not prove
public delivery. See the [publication contract](integration_contract.md).

## Schedules and task bounds


| Time / deployment | Exact operation and data movement |
|---|---|
| 03:00 `se3-backup` | Save checked data/models/publication history/results/tracking and online Prefect SQLite backup into `/backups`. Same-host copies need a separate off-host transfer. |
| 06:00 `se3-prepare` | Refresh A75 over [I−7,I+1); rebuild hourly target table. Build clusters from the seeded registry. Fetch MEPS/IFS run dates [I−10,I), so today's unavailable IFS cycle is not a training prerequisite. Fetch Previous Runs valid dates [I−10,I+3). Fit both saved models using the pre-issue rule, verify reload, promote, publish status. Existing historical caches are still required. |
| 08:55 `se3-capture` | Request next-day public A69/A18 wind/solar document; require a complete wind curve received before 09:00; record missing/late/error evidence. Failure does not substitute an unverified historical public curve or a different forecasting model. |
| 09:00 `se3-forecast` | Fetch MEPS/IFS run dates [I,I+1), Previous Runs valid dates [I,I+3). Load that issue's checked promoted model and its saved lag history; build delivery-day features without target actuals; validate source-time/grid/required weather/capacity; predict and repeat hourly quantiles; save immutable candidate inputs/forecasts; commit a complete public generation and confirm actual delivery. No fitting. |
| 09:30 deadline | A later verified delivery is late and cannot become an on-time scored issue. The forecast flow checks its window before/after fetching and after delivery. |
| 15:00 `se3-score` | Refresh A75 over the current [I−7,I+1) window and rebuild targets; recompute scores for first eligible issues whose actual delivery days are complete; publish actuals and provisional scores. At 15:00 the same issue's next-day actuals are not yet available: it scores earlier deliveries, with later retries on subsequent days. |
| Every 15 minutes `se3-status` | Commit due-day/job/model/collection status and any available scores. Fresh export time does not make an old forecast current. |

Date bounds above are half-open. `openmeteo.pull` converts them to inclusive API
`end_date=end−1 day`; MEPS/IFS iterate run dates. Pullers reuse cached identical
requests/runs, rather than re-downloading every listed date. Parsed stores merge
new rows; exact raw and cache paths are defined in each source module.
Registry, zone definitions, historical training weather, A68 audit data and initial
data volume are **bootstrap/manual inputs**, not silently fetched by every job.
No monthly final-evaluation or automatic model-tuning job runs in production.

Prefect task bounds are in `flows.py`: actuals 300 s with two retries (20 s delay),
weather 600 s with one retry (20 s), preparation 1800 s without retries, prediction
180 s without retries, capture 120 s with one retry (10 s), delivery 120 s with
two retries (5 s); whole flow 3000 s without flow retries. Source clients also have
HTTP timeouts/backoff where implemented. MEPS's production xarray/netCDF transport
does not use the separate ASCII helper's HTTP retry settings; its enclosing
weather task supplies the explicit 600-second workflow bound. One runner slot and shared file lock prevent overlapping
producer operations. Scheduled runs retain their original intended day after
restarts; expired preparation/collection/forecast runs fail visibly rather than
backdating fresh data. See `requested_day`, `execute`, `deployments` and `start`.

The [German product commands](dataflow.md#4-de-lu-solar) remain **manual only** in this stack. They
fit during their command, require their own cached histories/weather and use the
older append-only archives. Running a manual German command does not enrol it in
SE3's atomic live overlay or start a German schedule. Bundled case studies remain
available without continuing German production.

## Daily local trial

The old local trial remains the active schedule until the owner's Prefect cutover.
The installer and shell wrapper have been retired from this checkout. The three
existing user services use the checked source from commit
`20b607b` in
`../grid-signals-preserved/2026-11-01-before-2b/source` (relative to the repository root),
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

## Preservation and source consolidation — 2026-11-01

Original source, data, archive checksums and exact-evaluation recovery instructions
are in the [preservation record](archive/operations-record.md#preservation-and-source-consolidation--2026-11-01).
[Local deployment checks](archive/operations-record.md#local-verification--2026-11-01)
record measured reload, resource, restart and restore results.
