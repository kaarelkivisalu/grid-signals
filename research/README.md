# Day-ahead wind and solar forecasting

Electricity for tomorrow is bought and sold today. Bidding for a given day closes at
midday the day before, so everyone trading has to guess how much wind and solar will
actually generate over the 24 hours that follow. Wind is the least predictable part of
the supply, which makes it the hardest part of that guess to get right.

This project builds that guess. Every morning it takes the overnight weather forecasts,
converts them into expected generation for each hour of tomorrow, and reports not just
a single number but a **range**: how much output is likely, and how confident we
should be.

| | where it stands (2026-10-15) |
|---|---|
| **Wind, SE3** (central Sweden) | Working end to end; the daily job is not yet scheduled. Corrected quarter-hour winter evaluation: **2.90% nMAE**, **72%** coverage for nominal 80% ranges, over **79 days** |
| **15-minute output** | Implemented and evaluated on genuine quarter-hours. Default repeats hourly forecasts after interpolation showed no significant CRPS gain; interpolation is optional. See `reports/products_15min.md` |
| **Solar** (Germany) | First DE-LU quarter-hour forecasts: **1.96% daylight nMAE** over **90 winter days**, ahead of the three references. Fleet and annual capacity approximations are documented in `reports/products_15min.md` |
| **Other bidding zones** | Not started. Resource and per-zone assessment in `docs/roadmap.md` §6 |

What is planned next, and why, is in **`docs/roadmap.md`**. The sources behind the
methods are reviewed in **`docs/literature.md`**.

![](reports/figures/task_horizon.png)

---

## What a forecast looks like

A forecast for a delivery day, made the morning before:

![](reports/figures/latest_forecast.png)

The dark line is the median output for each interval. The shaded bands say how
uncertain that is: the darkest covers the middle half of plausible outcomes, the palest
covers all but the most extreme 10%. A wide band means the weather is genuinely hard to
call that interval; a narrow one means we expect to be close. The chart shows the newest
forecast on file. Operational output defaults to 15-minute intervals; the daily job is
not yet scheduled. The solar chart and new product evaluations are in
[`reports/products_15min.md`](reports/products_15min.md).

The same method on four days from the past, picked by rank rather than by hand: an
average day, a poor one, the worst in the period, and the windiest.

![](reports/figures/backtest_examples.png)

---

## How good is it

The figures below describe the archived September hourly board. They predate the
October correction that dates forward weather features to their latest input
(+3 hours). Use `reports/products_15min.md` for the corrected current product
evaluation; the older hourly numbers are historical, not a current accuracy claim.

![](reports/figures/leaderboard_crps.png)

Each bar is a different method, all measured the same way: run it on seventeen months of
past days it was never trained on, and see how far it lands from what actually happened.

| method | what it actually does |
|---|---|
| Repeat what happened 48 h ago | Generation two days earlier, copied forward. The crudest possible guess |
| Long-run average | The average output for this hour of the day and time of year, ignoring the weather |
| Straight line through 8 physics numbers | A linear formula over forecast wind speed, the turbine power curve and the time of year |
| Turbine power curve, nothing learned | Forecast wind at 8 locations across SE3, through a manufacturer-style power curve, weighted by the capacity near each location. No fitting |
| Boosted trees, single guess + spread | LightGBM over 155 inputs, predicting one number, with the uncertainty estimated afterwards |
| Boosted trees, full range of outcomes | The same model family, trained to predict the whole range directly. **This is what the project ships** |
| Grid operator's published forecast | Svenska kraftnät's own numbers, for reference only (see below) |

The inputs are mostly forecast weather at 8 points spread across the zone, from five
weather models:
- **Three global models** (ECMWF, GFS, ICON) from an archive that can only be asked for
  forecasts "as they stood a whole number of days earlier".
- **MET Norway's 2.5 km MEPS and ECMWF's 9 km IFS**, addressed by the specific model run
  that would have been in hand at 09:00 UTC.

Also included: how much the models disagree, how the weather changes hour to hour, the
time of year, and what the fleet generated two or more days ago.

**What the chart says:**
- **Physics gets you most of the way.** The power curve alone misses by 166 MW. Machine
  learning takes that to 120 MW: a 28% gain in the headline score (CRPS), up from 15%
  when only the whole-day archive was used. This is a physics problem with a
  statistical correction on top.
- **Weather-blind methods are hopeless.** The seasonal average misses by 783 MW. That gap
  is the value of using weather forecasts at all.
- **The grid operator's 69 MW is not a fair comparison.** The public archive serves the
  *latest revised* version of that forecast, with corrections made after bidding closed.
  Published day-ahead skill for a zone this size is 140–280 MW. Treat it as a yardstick,
  not a competitor. An honest comparison needs the forecast captured at issue time
  (roadmap §0).

### What changed on 2026-09-21/22

| change | effect | details |
|---|---|---|
| Weather addressed by model run (MEPS + IFS) alongside the whole-day archive | nMAE −12%, CRPS −11%; the jump in error at lead hour 34 falls from +45% to about +20% | `reports/meps_archive.md` |
| Calibration grouped by how much the weather models disagree | 80% coverage 0.74 → 0.77 at equal CRPS; coverage now even across calm and uncertain weather | `reports/products_15min.md` | quarter-hour wind and solar evaluation, forecasts and archive coverage |
| `reports/calibration.md` |
| Calibration fitted on out-of-sample predictions from the whole training window | CRPS −3.7%, coverage → 0.78, autumn 0.73 → 0.78 | `reports/calibration.md` |
| Fixed: missing weather values averaged into "zero wind" | one IFS run that came back empty had been read as dead calm (2025-08-08 forecast at half the actual output); a few Open-Meteo hours likewise | `features/wind.py` |

Full metric tables for both model versions are in `reports/modelling.md`.

---

## Known limitations

**1. Ranges are still slightly too narrow: 78% coverage at a nominal 80%.** The
worst remaining failure is a day on which the model is confidently wrong. On 13
February 2026 it over-forecast by about 520 MW for all 24 hours with an ordinary-width
range, in the old and new versions alike. Better weather data did not change it, which
points at the fleet (availability, icing), not the forecast. Coverage by forecast level
and by model disagreement:

![](reports/figures/coverage_by_output.png)

**2. A seasonal bias the model cannot remove.** It over-forecasts in winter and
under-forecasts in autumn, by roughly ±40 MW:

![](reports/figures/seasonal_bias.png)

The same pattern appears in a study that uses the *actual* weather
(`reports/era5_ceiling.md`), and removing the day-of-year inputs does not change it. So
it lives in the data (availability, icing, maintenance seasons), and fixing it needs an
outage or availability source (roadmap §5).

**3. A residual jump in error at lead hour 34.** Half of each delivery day was
forecast from weather a day staler than necessary, because the main archive can only
be asked for forecasts by whole days (`reports/openmeteo_vintage.md`). The run-addressed
sources remove most of the jump, but not all of it, because the model still uses the
whole-day block:

![](reports/figures/nmae_by_lead.png)

**4. The capacity figure drifts against reality.** The highest output reached relative
to registered capacity fell from 0.91 in 2018 to 0.79 in 2025, in all four Swedish
zones. With the weather held fixed, turbines added since 2018 deliver only ~70% of
what physics expects (`reports/era5_ceiling.md`). This matters little inside the
current two-year training window, but it blocks training on older history.

![](reports/figures/ceiling_drift.png)

**5. Quarter-hour wind still uses an hourly-trained model.** Weather is interpolated
before the power curve, and output is evaluated against real quarter-hour actuals.
Native quarter-hour training and joint ramp uncertainty remain open (§1).

**6. One zone only.** Every finding comes from SE3. Whether it transfers is the point of
roadmap §4 (SE4 as an in-country control, Finland as an out-of-country test).

**7. Production fitting needs complete weather coverage.** MEPS historical access is
working again and the archive refresh is tracked in `reports/products_15min.md`.
Production can use new observations without scoring the sealed holdout; development
is fixed to dates before 2026-03-20 even as inputs are refreshed.

**8. Solar is a first fleet approximation.** Six equal-area sites, fixed panel
orientations and annual ENTSO-E capacity snapshots stand in for a dated MaStR fleet.
It uses one pinned ECMWF Previous Runs model. These assumptions and measured interval
coverage must accompany its forecasts.

---

## Reference

### Documents

| document | what it settles |
|---|---|
| `docs/roadmap.md` | what is still to be done, in order, including the cost of scaling to other zones |
| `docs/literature.md` | the published record behind every method choice |
| `docs/metrics.md` | what every number means, and which rows it covers |
| `docs/dataflow.md` | where the data comes from and what is known when |
| `docs/integration_contract.md` | how this would plug into `grid-signals` |
| `reports/protocol.md` | the scoring rules, frozen before any model was built |
| `reports/data_audit.md` | which data is trustworthy enough to model |
| `reports/modelling.md` | leaderboards (v1 Open-Meteo only; v2 current), all metrics |
| `reports/calibration.md` | why the ranges were too narrow and what fixed most of it |
| `reports/meps_archive.md` | the run-addressed weather sources and their A/B tests |
| `reports/openmeteo_vintage.md` | the whole-day archive's timing problem |
| `reports/era5_ceiling.md` | how much the actual weather can explain; the added-capacity shortfall |

### Where the numbers come from

Every figure is generated from the backtest's own outputs, so a chart cannot drift away
from the number it illustrates. The current board covers **501 delivery days, 12,002
hours, 2024-10-02 → 2026-03-01**. These are the days that have every weather source,
scored over 17 rolling-origin folds with a 7-day embargo. A six-month holdout
(2026-03-20 → 2026-09-19) is sealed and will be opened once (roadmap §7). No
hyperparameters have been tuned: with two years of data that buys flattering numbers
rather than better forecasts.

### Progress

| phase | state |
|---|---|
| 1–3 dataflow, data audit, targets, frozen protocol, baselines | done |
| 4–5 weather features, modelling | done |
| 6 run-addressed weather (MEPS + IFS), calibration | done, shipped |
| 6 15-minute output | Stage 1 implemented; native wind training remains (roadmap §1) |
| 6 German solar | initial quarter-hour model implemented; registry fleet remains (roadmap §3) |
| 7 integration contract | drafted |
| 7 scheduled daily run and live trial | not started (roadmap §0, §7) |

### Rules the code holds to

- **All times are stored in UTC.** Local market time appears only when defining which
  hours belong to a delivery day, and in the charts.
- **Nothing becomes an input unless it was knowable at the issue time** (09:00 UTC).
  Every input column records how old its information is, and a test fails the build if
  any of them is too fresh. Run-addressed weather is dated to when the run was
  *published*, not when it started.
- **Never use a weather provider's automatic "best model" blend.** What it blends
  changes over time, and a model would learn that as if it were weather.
- **Errors are measured against installed capacity, not average output**, so they stay
  comparable across years as the fleet grows.
- **Every change is judged by a same-rows A/B** on the development folds, with a
  day-block bootstrap for significance.
- **Every number in a report comes from a function in `src/`**, so it can be re-derived.

### Layout

```
docs/      roadmap, literature review, dataflow, metrics, integration contract
configs/   base.yaml (incl. weather sources and calibration scheme) + experiments/
src/renewable_forecast/
  windows.py   issue times, delivery days, lead hours
  config.py    YAML load, deep merge, run fingerprint
  paths.py     every filesystem path, in one place
  store.py     parquet source of truth, DuckDB views over it
  sources/     ENTSO-E, Open-Meteo, MEPS, IFS single runs, ERA5, turbine registry
  targets/     what we are predicting, and the capacity denominator
  features/    weather to power conversion, and the design matrix
  evaluation/  splits, metrics, baselines
  models/      quantile boosters, conformal calibration, scenarios
  pipelines/   pulls, backtest, A/B comparisons, predict
  reporting/   every figure, generated from backtest outputs
notebooks/ exploration only -- may import from src/, never the reverse
tests/     time alignment, information-age guards, calibration, figure integrity
reports/   committed markdown + figures
data/      gitignored
mlruns/    gitignored (MLflow, SQLite backend)
```

### Running it

```bash
uv sync --group research
export PYTHONPATH=research/src

uv run python -m renewable_forecast.pipelines.data_audit      # data quality gate
uv run python -m renewable_forecast.pipelines.pull_meps       # MEPS backfill (--radius 4 for neighbourhoods)
uv run python -m renewable_forecast.pipelines.pull_ifs_runs   # IFS HRES 00z runs (--run-hour 18 for 18z)
uv run python -m renewable_forecast.pipelines.train           # backtest leaderboard
uv run python -m renewable_forecast.pipelines.pull_actuals    # refresh training observations (.env / ENTSOE_API_KEY)
uv run python -m renewable_forecast.pipelines.predict         # forecast tomorrow; 09:00 UTC
uv run python -m renewable_forecast.pipelines.predict --fuel solar  # DE-LU, 15-minute
uv run python -m renewable_forecast.pipelines.refresh_archives --status-only
uv run python -m renewable_forecast.pipelines.backtest_products --fuel wind_onshore
uv run python -m renewable_forecast.pipelines.backtest_products --fuel solar
uv run python -m renewable_forecast.reporting.products
uv run python -m renewable_forecast.reporting.figures         # regenerate every figure

# A/B comparisons (same rows and folds per arm)
uv run python -m renewable_forecast.pipelines.compare_meps --ifs            # weather sources
uv run python -m renewable_forecast.pipelines.compare_calibration --schemes # calibration
uv run python -m renewable_forecast.pipelines.compare_blocks --help         # feature blocks

uv run mlflow ui --backend-store-uri sqlite:///research/mlruns/mlflow.db
uv run pytest research/tests
```

The research dependencies are an opt-in group, so a plain `uv sync` keeps the
`grid-signals` environment lean. `research/` shares the root `pyproject.toml` rather
than being an installed package, which is why `PYTHONPATH` is needed outside pytest.
