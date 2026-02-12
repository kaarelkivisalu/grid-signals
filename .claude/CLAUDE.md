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

## Workflow

- After completing a unit of work, proactively commit using [Conventional Commits](https://www.conventionalcommits.org/).
- After completing a milestone or significant task, update `ROADMAP.md` to reflect current progress (e.g., mark checklist items as done with `[x]`, note completion status in milestone headers). The roadmap should always accurately represent the actual state of the project.
