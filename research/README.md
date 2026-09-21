# research/ — day-ahead VRE forecasting

Probabilistic forecasts of bidding-zone renewable generation, issued at 09:00 UTC for
the following delivery day. Standalone: nothing here is imported by `src/grid_signals/`,
and the only planned link is a written contract (`docs/integration_contract.md`).

| track | state | headline |
|---|---|---|
| **SE3 wind** | v1 scored, holdout sealed | nMAE **3.07%** of installed capacity, 15% better than a pure-physics baseline |
| **DE-LU solar** | **audit only** — no model, no features | target series validated as upscaled rather than metered-only; `features/solar.py` does not exist yet |
| SE3 solar | blocked, deliberately | series is physically credible, but no zonal capacity denominator exists to normalise it |

![](reports/figures/task_horizon.png)

## Where the wind model stands

![](reports/figures/leaderboard_crps.png)

Read the right panel, not the left. Beating climatology by 80% is table stakes — it only
proves the pipeline works. The number that says whether machine learning earned its place
is **0.0232 against the physical power-curve baseline's 0.0272**: a 15% CRPS gain for a
gradient-boosted model over a transform with no fitted parameters at all. The feature
importances agree that this is a physics problem with a statistical correction on top —
the power-curve transform and its one-hour lag carry 38% of total gain between them.

A69, the TSO's own published forecast, is drawn hatched because it is **not a bar to
clear**. ENTSO-E serves it at its latest revision, so it scores three times better than
published day-ahead wind skill and is an upper reference only.

## Three things that are wrong with it

**1. The intervals are too narrow.** The PIT histogram is U-shaped: reality lands outside
the predicted range more often than it should. 80% intervals cover 73.7%.

![](reports/figures/calibration.png)

Conformalising on held-out days took coverage from 0.612 to 0.737 and closed most of the
gap, but not all of it. Untried: a larger calibration fraction, the adaptive-conformal
update that `models/conformal.py` already implements but the pipeline does not drive, and
stratifying by season as well as lead hour.

**2. Half the delivery day is forecast from a day-old weather run.** This is the
largest fixable error in the model, and it is bigger than everything machine learning
bought.

![](reports/figures/nmae_by_lead.png)

Error against lead time is not the smooth gradient the phase report described — it is a
**step of 35% at lead hour 34**, and the earlier report missed it by averaging over three
coarse lead blocks. Two things change at that boundary at once: the delivery day crosses
into daylight, and Open-Meteo's Previous Runs API — addressable only in whole days — is
forced from `previous_day1` to `previous_day2`, so the back half of every delivery day is
served by a forecast 24 h older than the physics requires.

Lead hour and clock hour are perfectly collinear under a fixed issue time, so an ablation
was needed to separate them: force offset 2 onto *every* lead hour, and the front half
carries the stale vintage at unchanged clock hours.

![](reports/figures/vintage_ablation.png)

The answer is unambiguous. Forcing the stale vintage onto leads 22–33 raises their nMAE
from 0.0259 to 0.0376 (+45%) — *above* the back half's as-built 0.0351 — while leads
34–46, which already used offset 2, do not move (0.0351 → 0.0354, the control). At equal
vintage the night hours are slightly harder than the daylight ones, so the diurnal
explanation is not merely secondary, it has the wrong sign.

Extrapolating the front half's offset-1/offset-2 ratio to the back half puts overall nMAE
at roughly **0.025 against today's 0.0307** if the whole delivery day could be served from
one 00z run — an ~18% gain, larger than the 15% machine learning earned over physics.
Details and the fix: `reports/openmeteo_vintage.md`.

**3. The capacity denominator drifts, in every zone at once.**

![](reports/figures/ceiling_drift.png)

If the installed-capacity series tracked the fleet, the p99.9 of implied capacity factor
would sit flat near 0.90–1.00. It falls from 0.91 to 0.79 in SE3 between 2018 and 2025,
and all four Swedish zones fall together. Ruled out so far: curtailment (excluding
flagged hours moves the statistic by 0.001) and fleet spatial spread (which *narrowed*
over the period, and would push the ceiling up). The registry also agrees with ENTSO-E
A68 nationally to within a few percent in every year, so it is not a simple over-count.
Unresolved. It matters because ~7% of the drift falls inside the modelling window, and
the model's own error is 3%.

## What is next, in order

1. **Fix the vintage step** — needs an NWP archive addressable by run initialisation
   rather than by whole days. MET Norway's MEPS archive is confirmed to be exactly that,
   which turns the ensemble spike into the fix for the largest measured structural error,
   not just a nice-to-have. See `reports/meps_archive.md`.
2. **Close the calibration gap** — the three untried options above.
3. **Resolve the ceiling drift** — most likely candidates are A75 under-reporting a
   growing fleet, or registry commissioning dates that lead grid connection.
4. **Start DE-LU solar** — Phases 3–5 re-run with the existing scaffolding: MaStR fleet
   registry, more cluster points, `features/solar.py`, netztransparenz cross-check.
5. **Score the scenarios** — `models/scenarios.py` implements the Schaake shuffle and a
   Gaussian copula; neither is on the leaderboard, because separating them needs
   variogram and energy scores rather than marginal CRPS.
6. **Operational dry-run** — 30 consecutive scheduled runs, checking live nMAE stays
   within ~1.25× of backtest. Needs a month of elapsed time whenever it starts.

Not done and deliberately so: the 184-day holdout (2026-03-20 → 2026-09-19) has never
been opened, and there has been no hyperparameter search — with 763 development days,
tuning on the comparison folds would buy apparent skill at the cost of real skill.

## Phase status

| Phase | State |
|---|---|
| 1 — dataflow diagram + scaffold | done |
| 2 — data audit (hard gate) | done — `reports/data_audit.md`, GO for SE3 wind |
| 3 — targets, frozen protocol, baselines | done — `reports/protocol.md` |
| 4 — NWP feature pipeline | done — `reports/openmeteo_vintage.md`, design matrix built |
| 5 — modelling | done — `reports/modelling.md` |
| 6 — ensemble spike | done — `reports/meps_archive.md`, conditional GO |
| 6 — DE-LU solar | not started |
| 7 — integration contract | drafted — `docs/integration_contract.md` |
| 7 — operational dry-run | not started |

## Conventions

- **All times are tz-aware UTC** in storage and computation. Local time appears only when
  defining the delivery day.
- **Nothing is a feature unless it was knowable at 09:00 UTC on the issue day.** Every
  feature column carries a `max_source_time`; the leakage test asserts it.
- **Never use forecast blends** such as Open-Meteo's `best_match` for training — their
  composition changes over time, which is a silent non-stationarity.
- **Metrics are normalised by installed capacity**, not by mean generation, so they stay
  comparable across years as the fleet grows.
- **Every number and every figure in a report comes from a function in `src/`**, so it can
  be re-derived and cannot drift away from the claim it supports.

## Reports

| file | what it settles |
|---|---|
| `docs/dataflow.md` | the known / not-known boundary, and how sources reach the design matrix |
| `reports/data_audit.md` | Phase 2 gate: which targets are usable, and why A69 is not a benchmark |
| `reports/protocol.md` | the frozen evaluation protocol — splits, metrics, baselines |
| `reports/openmeteo_vintage.md` | what `previous_dayN` actually means, established empirically |
| `reports/modelling.md` | the leaderboard and what it says |
| `reports/meps_archive.md` | whether a real ensemble is available retroactively |
| `docs/integration_contract.md` | the table and tool signature `grid-signals` would consume |

The full plan (phases, gates, roadmap, failure modes) lives at `~/.claude/plans/`.

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
  reporting/   every figure in reports/, generated from backtest artifacts
notebooks/ exploration only -- may import from src/, never the reverse
tests/     time-alignment, leakage and figure-integrity tests
reports/   committed markdown + figures; every number re-derivable from src/
data/      gitignored
mlruns/    gitignored (MLflow, SQLite backend)
```

## Setup and running

The research stack is an opt-in dependency group, so a plain `uv sync` keeps the
`grid-signals` environment lean. `research/` shares the root `pyproject.toml` rather than
being an installed package, so the package is reached via `PYTHONPATH` — `pytest` needs
no such setup, since `pythonpath` is configured at the root.

```bash
uv sync --group research
export PYTHONPATH=research/src

uv run python -m renewable_forecast.cli info
uv run python -m renewable_forecast.pipelines.data_audit   # Phase 2 gate
uv run python -m renewable_forecast.pipelines.train        # backtest + leaderboard
uv run python -m renewable_forecast.reporting.figures      # regenerate every figure
uv run mlflow ui --backend-store-uri sqlite:///research/mlruns/mlflow.db

uv run pytest research/tests
```

If the `PYTHONPATH` friction becomes annoying, promoting `research/` to a uv workspace
member with its own `pyproject.toml` is a small change.
