# Grid Signals

Day-ahead electricity forecasting for the Nordic and Baltic markets, with
reproducible model comparisons and a public record of forecast performance.
An energy-sector ML portfolio covering modelling, evaluation and practical MLOps.

[Open the public demo](https://grid-signals-demotest.kaarelkivisalu.ee).
It presents historical SE3 wind and German solar, load and price case studies,
with uncertainty, actuals, matched comparisons and CSV downloads.

The destination is wind, solar and spot-price forecasts across 15 Nordic/Baltic
bidding zones. Current evaluated models cover SE3 onshore wind and DE-LU
solar/load/prices. Imported observations do not count as forecast coverage.
Daily SE3 operation is awaiting server deployment; see the [roadmap](ROADMAP.md)
for current status and delivery order.

## Run the local demo

Requires Docker and Docker Compose:

```bash
docker compose -f compose.demo.yaml up --build -d
```

Open **http://localhost:8502**. The bundled historical results need no API keys,
training or database. Wind opens on SE3's 2026-09-19 historical comparison.

View logs with `docker compose -f compose.demo.yaml logs -f`.
Stop the demo with `docker compose -f compose.demo.yaml down`.

## Develop locally

Requires `uv`; the full environment includes forecast and research dependencies:

```bash
uv sync --frozen --group research
uv run grid-signals ui
```

Open **http://localhost:8501**. The UI reads saved results; provider credentials
are needed only when fetching new data. Use `uv run grid-signals --help` to
explore commands.

## Find the right guide

| Task | Guide |
|---|---|
| See current priorities and remaining work | [Roadmap](ROADMAP.md) |
| Understand the package, services and design decisions | [Architecture](docs/implementation-plan.md) |
| Configure paths, run forecasts or refresh results | [Forecast operations](docs/operations.md) |
| Deploy, monitor or restore the producer | [SE3 deployment](docs/operations.md#se3-producer-deployment--milestone-2b) |
| Understand sources, features and model choices | [Model reference](docs/dataflow.md) |
| Interpret scores and evaluation populations | [Metrics](docs/metrics.md) |
| Check timing, publication identity and eligibility | [Publication contract](docs/integration_contract.md) |
| Review results or reproduce an evaluation | [Research evidence](research/README.md) |

## Run the CI checks locally

```bash
bash scripts/check.sh
```

This installs locked dependencies, checks lint and formatting, runs tests with
coverage and checks the web/runner images offline. Docker must be running for
image checks; builds need access to base images and dependencies. Tests use local
fixtures and a temporary Prefect server, so they need permission to start a local
server. No provider credentials are required.

For focused checks, append `lint`, `test`, `demo` or `runner` to the command.
Run individual tests with `uv run pytest <paths>`; fix formatting with
`uv run ruff format .`. Run the full script before pushing.

If the checkout moves, recreate its environment with
`uv venv --clear` followed by `uv sync --frozen --group research`.
