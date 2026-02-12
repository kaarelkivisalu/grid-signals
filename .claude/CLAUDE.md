# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

grid-signals — Nordic-Baltic Energy Intelligence Agent. Automated market analysis powered by structured data pipelines and LLM reasoning with tool use.

See `ROADMAP.md` for the full project plan and future directions.

### Architecture

- **Data ingestion:** ENTSO-E, Open-Meteo, Elering/Fingrid APIs → DuckDB
- **LLM agent:** Claude API with tool use, queries DuckDB through structured tools
- **Output:** Automated daily briefing (delivery channel TBD)

### Tech Stack

- Python 3.12+, DuckDB, entsoe-py, Claude API, pytest, uv

## Build & Test Commands

```bash
uv sync --all-extras   # install dependencies
uv run pytest tests/    # run tests
```

## CLI Commands

```bash
uv run python -m grid_signals daily       # ingest ENTSO-E data
uv run python -m grid_signals weather     # ingest weather forecasts
uv run python -m grid_signals backfill    # backfill date range
uv run python -m grid_signals validate    # run data quality checks
uv run python -m grid_signals briefing    # generate daily briefing (needs ANTHROPIC_API_KEY)
```

## DB Schema

- **Tables:** day_ahead_prices, generation_by_type, total_load, cross_border_flows, outages, weather_forecasts
- **Outages** uses `start_time`/`end_time` columns; all other tables use `timestamp`
- All inserts use upsert (`INSERT OR REPLACE`) for idempotency

## Data Quirks

- **DuckDB single-writer lock:** cannot run concurrent writes (e.g. daily + backfill simultaneously)
- **15-min ISP transition (mid-2025):** some data is hourly, some 15-min. Validation detects resolution dynamically from timestamp gaps (min_gap ≤ 15 → 15min mode)
- **ENTSO-E rate limit:** 400 req/min. PL zone has the most generation data (~37K rows/month). Backfill in 30-day chunks works well
- **Open-Meteo:** archive API for historical, forecast API for future; both free, no key needed
- **entsoe-py:** some zones have no data for certain types (e.g. SE4 outages returns empty)

## Testing

- Tests use in-memory DuckDB with mocked external clients
- E2E briefing test mocks Anthropic client but uses real DB tool execution

## Workflow

- After completing a unit of work, proactively commit using [Conventional Commits](https://www.conventionalcommits.org/).
- After completing a milestone or significant task, update `ROADMAP.md` to reflect current progress (e.g., mark checklist items as done with `[x]`, note completion status in milestone headers). The roadmap should always accurately represent the actual state of the project.
