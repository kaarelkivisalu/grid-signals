# Preservation and deployment records

Dated evidence, archived on 2026-11-02. Follow [current operations](../operations.md)
for commands; these checks do not establish current forecast production.

## Preservation and source consolidation — 2026-11-01


The pre-migration revision is `23986cfa73f93796e74882ce12c86a85f2f62790`.
Local preservation copies are outside this checkout at
`../grid-signals-preserved/2026-11-01-before-2a/`, relative to the repository root:

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
`../grid-signals-learning/notebooks/`, relative to the repository root. Local research data and
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
[path configuration](../operations.md#configure-paths-and-dependencies). To preview new exports,
set `GRID_SIGNALS_EXPLORER_PATH` to the exported `explorer` directory and
`GRID_SIGNALS_SNAPSHOT_PATH`, `GRID_SIGNALS_PRICE_SNAPSHOT_PATH` and
`GRID_SIGNALS_LOAD_SNAPSHOT_PATH` to the three exported summary files.

## Local verification — 2026-11-01


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
