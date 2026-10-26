# Grid Signals

Nordic/Baltic day-ahead power forecasting, reproducible model comparisons and a
public performance record. An employer-facing portfolio for energy-sector ML and
data science, demonstrating forecasting and practical orchestration/MLOps, with
useful agent/RAG applications to be evaluated later.

The destination is **wind, solar and day-ahead spot-price forecasts across all 15
regional bidding zones**: SE1–SE4, NO1–NO5, DK1–DK2, FI, EE, LV and LT. Onshore wind
comes first; offshore follows separately. This is the roadmap destination, not a
claim of current forecast coverage.

**Current milestone:** prepare the historical demo for public release, leading with SE3 wind
and retaining German forecasts as supporting case studies. Then expose daily
publication and performance through a consolidated forecasting product, transfer
wind to SE4 and improve the demo one feature at a time. The target uses one package
and CLI across local use and deployment, Prefect orchestration and a
website that reads saved forecast results. The original PostgreSQL/briefing/chat application will
be retired; standalone exercises move elsewhere. See the authoritative [roadmap](ROADMAP.md) and
[whole-project assessment and implementation plan](docs/implementation-plan.md).

## Run the local demo

The standalone image installs only the web dependencies and needs no credentials:

```bash
docker build -f Dockerfile.demo -t grid-signals-demo:local .
docker run --rm -p 127.0.0.1:8502:8501 grid-signals-demo:local
```

Open **http://localhost:8502**. The first view is **SE3 onshore wind on
2026-09-19**, with the evaluated model, physical reference, uncertainty and actuals.
Use the sidebar to inspect German solar, load and price case studies.

For development with the existing full project environment:

```bash
uv sync --frozen
uv run grid-signals ui
```

Open **http://localhost:8501**. Bundled results need no database, API keys,
research dependencies or model training.

- **Market explorer:** one market/date/target/model selection; aligned wind, solar,
  load, observed residual load and spot prices; forecast uncertainty and errors.
- **Performance:** full development/final archives; matched metrics by year,
  season, month, weekday and ordinal market quarter; CSV downloads.
- **European coverage:** offline clickable map distinguishing project data,
  unimported SDAC areas and adjacent markets outside SDAC.
- **Models & data:** model recipes, input features, resolution, cutoffs and public
  forecast comparison inventory.

Observations cover **11 areas**. Evaluated custom forecasts cover **DE-LU
solar/load/price and SE3 onshore wind**; imported data alone is not forecast skill.

These are research previews. A local forward publication trial has started;
always-on reliability has yet to be demonstrated. LEAR leads the German price benchmark and
is the forward publication baseline; its price intervals still under-cover on holdout.
Custom DE-LU load is implemented; its first price-input experiment shows no resolved gain.
Custom German wind and residual-load forecasts are deferred; observed residual
load is available where all components exist. The website exposes only the four
forecast views; the old database and chat tools are outside the demo.
Public hosting is handled by the project owner. See the
[local release review and deployment handoff](docs/demo-release.md).

See the [historical direction and commercial comparison](docs/project-direction-review.md),
[research results](research/README.md) and [operations guide](docs/operations.md).

## Refresh the portable results

After generating the underlying research results:

```bash
PYTHONPATH=research/src uv run --group research python -m renewable_forecast.reporting.export_demo
PYTHONPATH=research/src uv run --group research python -m renewable_forecast.reporting.export_price
PYTHONPATH=research/src uv run --group research python -m renewable_forecast.reporting.export_load
PYTHONPATH=research/src uv run --group research python -m renewable_forecast.reporting.export_explorer
```

The exporters read existing Parquet files and evaluation results, then update the
JSON summaries and historical result files in `src/grid_signals/app/assets/`.
Each Parquet filename includes a checksum of its contents. The file index is
updated last so incomplete updates are not shown. Exporting does not train models
or score holdouts. Bundles ship with the application; chart dates and publication status
describe the underlying forecast, rather than the export time.

Set `GRID_SIGNALS_EXPLORER_PATH` to preview another explorer directory. See the
[operations guide](docs/operations.md) for fetching additional market data.

## Implementation transition

The current checkout still contains the original PostgreSQL market dashboard,
briefings/chat, ingestion-oriented CLI and local forecast timers. They have not
been removed. They are not permanent supporting products in the target architecture.
Forecast production currently uses the [research entrypoints](research/README.md#run-the-research).
The code-reorganisation milestone replaces the split runtimes with one package/CLI and
Prefect lifecycle while preserving evaluated results and publication evidence.
See the [implementation plan](docs/implementation-plan.md) for keep/remove decisions
and the [publication contract](research/docs/integration_contract.md) for reliability.
