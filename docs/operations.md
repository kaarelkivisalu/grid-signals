# Local forecast operations

Milestone 2a consolidates forecasting in the installed `grid_signals.forecast`
package and `grid-signals` CLI. The original PostgreSQL ingestion and briefing/chat
runtime has been removed. Existing local forecast timers remain temporarily;
Prefect cutover, saved trained models and always-on operation are milestone 2b.

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

For exact original evaluation reproduction, work in a separate restored directory,
install its original locked environment, and use its original `research/src`
imports and cached inputs. Do not rewrite old source paths or checksums to point
at moved files. The consolidated package has a separate code version record at
`src/grid_signals/forecast/configs/releases/consolidated_v1.json`. New publications
verify this record and use its identity. It links the historical records and load
selection by checksum without claiming a new final evaluation. A new code/settings
revision requires a new record, created with `grid-signals version --register PATH`
and selected through `GRID_SIGNALS_VERSION_RECORD`; this is code identity, not the
saved-trained-model promotion planned in 2b.

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

This is the existing trial mechanism, scheduled for retirement after Prefect
cutover. Do not add another active scheduler for the same production issues.

After `uv sync --group research`:

```bash
uv run python scripts/install_forecast_schedule.py
systemctl --user list-timers 'grid-signals-*'
```

The installer writes user services/timers for this checkout's virtualenv. During
2a, the three existing services were updated to this checkout and
`python -m grid_signals workflow MODE`; their former lowercase checkout paths
were stale. Systemd was reloaded without starting jobs or changing timers. All
three timers remained active and waiting. The original unit files are preserved
in the directory above. This confirms configuration only, not a successful daily run.

The schedule remains:

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

## Refresh the historical explorer

The website has one shared market/date/target/model selection, full backtest
series and grouped diagnostics. Exporting reads **completed** research evaluations;
it never trains or reopens a sealed holdout:

```bash
uv run grid-signals export explorer
```

The daily results-export job also runs this exporter. Files are named using checksums and the
file index (`manifest.json`) changes last, so a failed refresh leaves the previous generation readable.
Old generations can be removed when no running reader needs them. The web image
contains the exported result files, not the raw cache.

Generated Parquet exports are ignored by Git; the files already committed remain
tracked. Exports default to `data/exports`; use
`uv run grid-signals --output-dir src/grid_signals/app/assets export all` only
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
Dockerfile were removed in 2a; the forecast runner deployment follows in 2b.
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
The current Compose files do not implement that target; do not deploy the original
market stack unchanged as the forecast producer.

Existing Dokploy capacity hosts the test site; reconsider hosting only for a
concrete operational or cost constraint. The
[roadmap](../ROADMAP.md) defines release acceptance; the
[historical direction review](project-direction-review.md) retains the comparison.
