# research — day-ahead VRE forecasting

Standalone model-development work: probabilistic day-ahead forecasting of variable renewable
generation. **Wind on SE3** first, **solar on DE-LU** second.

This is deliberately **not integrated** with `grid-signals`. The only integration deliverable is a
written contract (`docs/integration_contract.md`, Phase 7). Nothing here is imported by
`src/grid_signals/`.

## Start here

- **[`docs/dataflow.md`](docs/dataflow.md)** — the living diagram: the forecast task in time, the
  known/not-known boundary at issue time, the pipeline, storage and evaluation flow. Read this
  before anything else, and amend it whenever the pipeline shape changes.
- The full plan lives at `~/.claude/plans/` (phases, gates, roadmap, failure modes).

## Setup

The research stack is an opt-in dependency group, so a plain `uv sync` keeps the `grid-signals`
environment lean.

```bash
uv sync --group research
```

Because `research/` shares the root `pyproject.toml` rather than being an installed package, the
package is reached via `PYTHONPATH`:

```bash
export PYTHONPATH=research/src
uv run python -m renewable_forecast.cli info
```

`pytest` needs no such setup — `pythonpath` is configured in the root `pyproject.toml`:

```bash
uv run pytest research/tests
```

If the `PYTHONPATH` friction becomes annoying, promoting `research/` to a uv workspace member with
its own `pyproject.toml` is a small change.

## Layout

```
docs/      dataflow.md (living), integration_contract.md (Phase 7)
configs/   base.yaml + experiments/ deep-merged on top
src/renewable_forecast/
  windows.py   temporal contract: issue times, delivery days, lead hours
  config.py    YAML load, deep merge, run fingerprint
  paths.py     every filesystem path, in one place
  store.py     parquet source of truth, DuckDB views over it
  sources/ targets/ features/ evaluation/ models/ pipelines/
notebooks/ exploration only -- may import from src/, never the reverse
tests/     time-alignment and leakage property tests
reports/   committed markdown + plots; every number re-derivable from src/
data/      gitignored
mlruns/    gitignored (MLflow local file backend)
```

## Conventions

- **All times are tz-aware UTC** in storage and computation. Local time appears only when defining
  the delivery day.
- **Nothing is a feature unless it was knowable at 09:00 UTC on the issue day.** Every feature column
  carries a `max_source_time`; the leakage test asserts it.
- **Never use forecast blends** such as Open-Meteo's `best_match` for training — their composition
  changes over time, which is a silent non-stationarity.
- **Metrics are normalised by installed capacity**, not by mean generation, so they stay comparable
  across years as the fleet grows.
- Every number in a report comes from a function in `src/`, so it can be re-derived.

## Status

Phase 1 (dataflow diagram + scaffold) is done. Phase 2 is the data audit, which is a **hard gate** —
no modelling code until `reports/data_audit.md` carries an explicit GO/NO-GO per target.
