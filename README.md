# Grid Signals

Nordic/Baltic day-ahead electricity forecasting, reproducible model comparisons and a
public performance record. An employer-facing portfolio for energy-sector ML and
data science, demonstrating forecasting and practical orchestration/MLOps, with
useful agent/RAG applications to be evaluated later.

The destination is **wind, solar and day-ahead spot-price forecasts across all 15
regional bidding zones**: SE1–SE4, NO1–NO5, DK1–DK2, FI, EE, LV and LT. Onshore wind
comes first; offshore follows separately. This is the roadmap destination, not a
claim of current forecast coverage.

**Current milestone:** the SE3 saved-model workflow (2b) is implemented and locally
verified. Manual server deployment and scheduler cutover remain; daily public
operation is not yet established. The historical demo is public. One installed
`grid_signals.forecast` package and `grid-signals` CLI serve local and scheduled runs. See the
[roadmap](ROADMAP.md) and [implementation plan](docs/implementation-plan.md).

## Run the local demo

With Docker and Docker Compose installed, start the demo with one command:

```bash
docker compose -f compose.demo.yaml up --build -d
```

Open **http://localhost:8502**. Overview leads with **SE3 onshore wind on
2026-09-19**, comparing the model, physical reference, uncertainty and actuals.
The sidebar links directly to wind, solar, prices, demand, performance, coverage and methods.

The standalone image installs only the web dependencies and needs no credentials.
View logs with `docker compose -f compose.demo.yaml logs -f`. Stop and remove the
demo container with `docker compose -f compose.demo.yaml down`.

For development with the existing full project environment:

```bash
uv sync --frozen
uv run grid-signals ui
```

Open **http://localhost:8501**. Bundled results need no database, API keys,
forecast runner dependencies or model training.

- **Overview:** area/date selection, one electricity-price graph and one combined
  wind, solar and demand graph. Each product has at most one saved model forecast;
  observations remain visible where no evaluated forecast exists.
- **Wind, Solar, Prices and Demand:** choose an area and date to see the selected
  model, named reference, actuals, an 80% range, errors and CSV downloads. The date
  chooses historical evaluation, development results or a published forecast
  automatically; alternative models and earlier publications are optional.
- **Performance:** matched model comparisons with score explanations and monthly
  error patterns. Period, model and normalisation controls are optional.
- **Map:** all 39 SDAC bidding zones and a full colour-coded availability table.
  Map areas and cells link directly to their saved data; unsupported areas remain visible.
- **Models & data:** input-to-forecast diagrams explain each approach before its
  regional applications. Detailed sources, recipes and fitting rules can be expanded.

Area buttons join edge to edge within groups, with small gaps between countries
and EE/LV/LT together. Country names are available on hover. Selectors show the
regional project areas plus other areas with saved data; Map shows every SDAC area.
Unavailable areas are greyed out for each page. Product selectors use the same
joined buttons as area selectors. Models & data explains approaches independently
of the selected area; detailed controls and recipes use expandable sections.
Delivery dates use one compact control: a calendar between two arrow buttons
that step between saved days. A date without a saved forecast shows an empty
state. Fundamentals use MW, with labels and tooltips rounded to whole MW.

Observations cover **11 areas**. Evaluated custom forecasts cover **DE-LU
solar/load/price and SE3 onshore wind**; imported data alone is not forecast skill.

These are research previews. A local forward publication trial has started;
always-on reliability has yet to be demonstrated. LEAR leads the German price benchmark and
is the forward publication baseline; its price intervals still under-cover on holdout.
Custom DE-LU load is implemented; its first price-input experiment shows no resolved gain.
Custom German wind and residual-load forecasts are deferred; observed residual
load is available where all components exist. The German demand study is available
from Demand in the sidebar. The old database and chat tools are outside the demo.
The historical demo is deployed through Dokploy at
[grid-signals-demotest.kaarelkivisalu.ee](https://grid-signals-demotest.kaarelkivisalu.ee)
from `feat/electricity-forecasting`. Once the roadmap is reasonably complete and
merged into `main`, the planned domain is `https://grid-signals.kaarelkivisalu.ee`.
See the [release review and deployment details](docs/operations.md#public-hosting).

See the [historical direction and commercial comparison](docs/project-direction-review.md),
[research results](research/README.md) and [operations guide](docs/operations.md).

For each serving model's **exact data sources, fetched fields, derived features,
architecture, reasons for selection, backtests/results and production schedule**,
start with the [serving-model guide](research/docs/dataflow.md). It links the
implementing functions and frozen evidence, and distinguishes scheduled SE3 from
the German manual case studies and research-only alternatives.

## Run the CI checks locally

With `uv` installed and Docker running, run all checks before pushing:

```bash
bash scripts/check.sh
```

This installs the locked development and research dependencies, checks lint and
formatting, runs the full test suite with coverage (local fixtures and a temporary
Prefect server), then checks the web and runner images without network access or
API keys. It stops at the first failed check. Image checks need Docker; builds
need access to the base images and locked dependencies. Tests need permission to
start a local server; PostgreSQL is not required.

For a shorter feedback loop, run one check group:

```bash
bash scripts/check.sh lint
bash scripts/check.sh test
bash scripts/check.sh demo
bash scripts/check.sh runner
```

GitHub Actions uses these same commands. Ruff and pytest come from `uv.lock`, so
CI uses the same tool versions as local checks. The lint command needs no Docker.
Checks report issues without changing source files; fix formatting with
`uv run python -m ruff format .` and rerun the checks.

If you move or rename the checkout, recreate `.venv` with
`uv venv --clear && uv sync --frozen --group research` so installed command paths
point to its new location.

## Refresh the portable results

After generating the underlying research results:

```bash
uv sync --frozen --group research
uv run grid-signals export all
```

The default export commits a complete checked generation to `data/exports/`,
including historical results, live forecasts, actuals and publication status.
The web reader pins that generation and falls back to the previous checked
generation or bundled history if needed. Exporting alone does not start a trial.
Use `--output-dir /absolute/results` before `export` to choose another destination.
Bundled website assets are updated only with an explicit
`uv run grid-signals --output-dir src/grid_signals/app/assets export all --historical`.
Each Parquet filename includes a checksum of its contents. The file index is
updated last so incomplete updates are not shown. Exporting does not train models
or score holdouts. Bundles ship with the application; chart dates and publication status
describe the underlying forecast, rather than the export time.

Set `GRID_SIGNALS_RESULT_ROOT=/absolute/results` to preview a daily result root.
`GRID_SIGNALS_EXPLORER_PATH` still supports a flat historical explorer. See the
[operations guide](docs/operations.md) for fetching additional market data.

## Forecast commands and configuration

```bash
uv sync --frozen --group research
uv run grid-signals info
uv run grid-signals fetch-actuals 2026-10-01 2026-10-15
uv run grid-signals refresh-weather --help
uv run grid-signals train --help
uv run grid-signals backtest --fuel wind_onshore
uv run grid-signals model prepare --issue-day YYYY-MM-DD
uv run grid-signals model validate --issue-day YYYY-MM-DD --model-id MODEL_ID
uv run grid-signals model promote --issue-day YYYY-MM-DD --model-id MODEL_ID --reason "Reviewed reload and training cutoff"
uv run grid-signals workflow forecast --issue-day YYYY-MM-DD --no-refresh
uv run grid-signals score --product se3-wind
uv run grid-signals export all
uv run grid-signals version
```

Replace the dates and model ID with the intended issue and the preparation output.
SE3 prediction loads an explicitly promoted model; it does not fit. Preparation
must finish before the 09:00 UTC issue cutoff. The daily Prefect preparation flow
fetches data, trains, validates and promotes under the declared daily policy.
`forecast` and the scheduled flow share real creation/delivery timing; historical
invocations do not become on-time evidence. German case-study forecasts retain
their manual fitting path and have no new schedules. `train` fits and scores the existing development
comparison, while `backtest` runs the quarter-hour product comparison. Neither
reopens a final evaluation. Use `--help` for each command's options.

The single lockfile has `web`, `runner`, `research` and `dev` dependency groups.
For a web environment use `uv sync --frozen --no-default-groups --group web`;
for forecasting use `uv sync --frozen --no-default-groups --group runner`.
The full development environment uses `uv sync --frozen --group research`.
MLflow and plotting tools are experiment dependencies; PostgreSQL, chat clients,
DuckDB and generic notebook packages are no longer required.

Set `GRID_SIGNALS_DATA_DIR`, `GRID_SIGNALS_OUTPUT_DIR`,
`GRID_SIGNALS_CONFIG_DIR`, `GRID_SIGNALS_REPORTS_DIR` or
`GRID_SIGNALS_MLRUNS_DIR` before importing pipelines. The matching CLI options
(`--data-dir`, `--output-dir`, etc.) go before the command. Data defaults to
`research/data`, exports to `data/exports`, reports to `research/reports` and
MLflow to `research/mlruns`, relative to the working directory. Settings ship in
`src/grid_signals/forecast/configs`. Absolute paths support mounted volumes and
running outside the checkout. Existing local inputs have not moved.

The original market database application, briefing/chat pages, duplicate forecast
pages and market deployment definitions have been retired. No Docker service or
volume was deleted during consolidation. The existing local forecast timers remain
until the Prefect cutover and use preserved 2a source. The new
`compose.forecast.yaml` runs a persistent Prefect server, runner and result-reading
web service, with schedules paused initially. Follow the
[manual deployment steps](docs/operations.md#se3-producer-deployment--milestone-2b)
to seed data, prepare a model, disable the old timers and activate the new schedule.
