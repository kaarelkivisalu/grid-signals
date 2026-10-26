# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

grid-signals — an employer-facing ML/data-science portfolio for Nordic/Baltic
day-ahead wind, solar and spot-price forecasting and practical orchestration/MLOps,
with reproducible comparisons and a public publication/performance record. Lead with SE3 wind; retain German
results as supporting case studies. Agent/RAG integration is a later usefulness
evaluation, not the product's core or an automatic feature requirement.

`ROADMAP.md` is the authoritative direction and delivery order;
`docs/implementation-plan.md` evaluates the whole repository and records subsystem
ownership, integration gaps and milestone prerequisites. Read both before feature
implementation, including their treatment of Prefect, notebooks, CLI tools and
the planned combination and removal of separate data paths. Existing code has
no automatic retention requirement. Standalone exercises belong outside the
focused forecast product. Deliver one bounded demo improvement at a time. Do not
implement later roadmap milestones as part of an earlier task. Older direction
reviews and research backlogs are historical.

### Target architecture

- **One installed product:** bring forecasting code together into `grid_signals`; one CLI and shared functions serve local runs, experiments and deployment. Current research code still lives under `research/` until migration.
- **Public website:** Streamlit reads published JSON/Parquet. It does not train or require the original market database.
- **MLOps:** Prefect orchestrates the forecast lifecycle; saved trained models with recorded versions, explicit promotion, experiment tracking and immutable forecast records provide the evidence.
- **Retire:** original PostgreSQL market application, generic chat/briefings, stale CLI/scripts, duplicate pages and local forecast timers after verified cutover. Preserve frozen scientific evidence and required data before code removal.
- **Publication:** local trial infrastructure exists; always-on public delivery and reliability remain work. `research/docs/integration_contract.md` defines publication semantics, not a requirement to build a database feed.

### Tech Stack

- Target: Python 3.12+, entsoe-py/weather clients, Parquet, Streamlit, Prefect, MLflow, pytest and uv; web/runner/experiment dependency profiles. PostgreSQL/psycopg and Anthropic are legacy dependencies planned for removal with their products.

## Build & Test Commands

```bash
uv sync          # install dependencies
uv run pytest    # run tests
```

## Current CLI Commands — transitional

These include legacy market commands scheduled for retirement. Do not build new
features on that application by default. Actual forecast commands are currently
documented in `research/README.md`; the target is a single product CLI.

```bash
uv run grid-signals daily       # ingest ENTSO-E data
uv run grid-signals weather     # ingest weather forecasts
uv run grid-signals backfill    # backfill date range
uv run grid-signals validate    # run data quality checks
uv run grid-signals briefing    # generate daily briefing (needs ANTHROPIC_API_KEY)
uv run grid-signals ui          # launch Streamlit web interface

# Query subcommands (direct tool access, no LLM needed)
uv run grid-signals query prices EE 2024-01-15 2024-01-16
uv run grid-signals query generation EE 2024-01-15 2024-01-16 --fuel-type wind_onshore
uv run grid-signals query weather EE_tallinn 2024-01-15 2024-01-16
uv run grid-signals query outages FI --fuel-type nuclear --active-at 2024-01-15
uv run grid-signals query flows EE FI 2024-01-15 2024-01-16
uv run grid-signals query load EE 2024-01-15 2024-01-16
uv run grid-signals query spread EE FI 2024-01-15 2024-01-16
uv run grid-signals query similar-days EE EE_tallinn --wind 7.0 --temp -5.0
```

## DB Schema

- **Tables:** day_ahead_prices, generation_by_type, total_load, cross_border_flows, outages, weather_forecasts
- All tables use `period_start`/`period_end` columns for time ranges
- All inserts use upsert (`ON CONFLICT ... DO UPDATE SET`) for idempotency

## Data Quirks

- **15-min ISP transition (mid-2025):** some data is hourly, some 15-min. Validation detects resolution dynamically from `period_start` gaps (min_gap ≤ 15 → 15min mode)
- **ENTSO-E rate limit:** 400 req/min. PL zone has the most generation data (~37K rows/month). Backfill in 30-day chunks works well
- **Open-Meteo:** archive API for historical, forecast API for future; both free, no key needed
- **entsoe-py:** some zones have no data for certain types (e.g. SE4 outages returns empty)

## Testing

- Tests use PostgreSQL via testcontainers (requires Docker) with mocked external clients
- E2E briefing test mocks Anthropic client but uses real DB tool execution
- Session-scoped container fixture shared across all tests; tables dropped/recreated per test

## Workflow

- After completing a unit of work, proactively commit using [Conventional Commits](https://www.conventionalcommits.org/).
- After completing a milestone or significant task, update `ROADMAP.md` to reflect current progress (e.g., mark checklist items as done with `[x]`, note completion status in milestone headers). The roadmap should always accurately represent the actual state of the project.
