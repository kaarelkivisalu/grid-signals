# Day-ahead wind and solar forecasting

Electricity for tomorrow is bought and sold today. Bidding for a given day closes at
midday the day before, so everyone trading has to guess how much wind and solar will
actually generate over the 24 hours that follow. Wind is the least predictable part of
the supply, which makes it the hardest part of that guess to get right.

This project builds that guess. Every morning it takes the overnight weather forecast,
converts it into expected generation for each hour of tomorrow, and reports not just a
single number but a **range**: how much output is likely, and how confident we should be.
It currently covers **onshore wind in SE3** (central Sweden). Solar is planned and not
yet started.

| | where it stands |
|---|---|
| **Wind, SE3** | Working. Typical miss **122 MW** per hour against 4,656 MW installed (was 143 MW on 2026-09-20) |
| **Solar** | Not started. Only the data checks are done |

![](reports/figures/task_horizon.png)

---

## What a forecast looks like

Here is tomorrow, made this morning. Nothing has happened yet, so there is nothing to
compare it against — this is the actual product:

![](reports/figures/latest_forecast.png)

The dark line is the single most likely output for each hour. The shaded bands say how
uncertain that is: the darkest covers the middle half of plausible outcomes, the palest
covers all but the most extreme 10%. A wide band means the weather is genuinely hard to
call that hour; a narrow one means we expect to be close.

This forecast says the wind drops away through the night and stays low all day — from
about 1,800 MW at midnight down to roughly 200 MW by lunchtime.

And here is the same method on four days from the past, where we *can* check it. The
days are picked by rank, not by hand — an average day, a poor one, the worst in the
whole period, and the windiest:

![](reports/figures/backtest_examples.png)

---

## How good is it

![](reports/figures/leaderboard_crps.png)

Each bar is a different method, all measured the same way: run it on seventeen months of past
days it was never trained on, and see how far it lands from what actually happened.

| method | what it actually does |
|---|---|
| Repeat what happened 48 h ago | Yesterday's generation, copied forward. The crudest possible guess |
| Long-run average | The average output for this hour of the day and time of year, ignoring the weather entirely |
| Straight line through 8 physics numbers | A simple linear formula over forecast wind speed, the turbine power curve, and the time of year |
| Turbine power curve, nothing learned | Pure physics: take forecast wind speed at each of 8 locations across SE3, push it through a manufacturer-style power curve, weight by how much capacity sits near each location. No fitting at all |
| Boosted trees, single guess + spread | A machine-learning model (LightGBM) over 155 inputs, predicting one number, with the uncertainty estimated separately afterwards |
| Boosted trees, full range of outcomes | The same model family, but trained to predict the whole range directly. **This is what the project ships** |
| Grid operator's published forecast | Svenska kraftnät's own numbers, for reference only — see the caveat below |

The 155 inputs are mostly forecast weather at 8 points spread across the zone. Three
global models come from an archive addressed by whole days (see problem 2). Two more
come from archives addressed by model run: MET Norway's 2.5 km MEPS and ECMWF's 9 km
IFS. On top of that: how much the models disagree with each other, how the weather is
changing hour to hour, the time of year, and what the fleet generated two or more days
ago.

**Three things are worth noticing.**

Physics alone gets you most of the way. A power curve with nothing learned lands at
166 MW; the machine-learning model takes that to 122 MW. Real, and worth having, but
this is a physics problem with a statistical correction on top — not a problem machine
learning solves by itself.

Weather-blind methods are hopeless. Guessing from the seasonal average misses by 780 MW,
six times worse. That gap is the whole value of using a weather forecast at all.

**The grid operator's number is not a fair comparison.** It looks far better than
everything else, at 69 MW. It should not be: published research puts realistic day-ahead
wind forecasting in the 140–280 MW range for a zone this size. The reason is that the
public data archive serves the *latest revised version* of that forecast, with
corrections folded in after the fact, and offers no way to retrieve what was actually
published before bidding closed. So it is a yardstick for how good this could eventually
get, not a competitor we are losing to.

---

## What is wrong with it

### 1. When we say 80% sure, we were right 74% of the time (now 78%)

The forecast claims a range it expects the truth to fall inside 80% of the time. Across
13,082 hours the truth actually landed inside it 74% of the time. The ranges are too narrow
— the model is more confident than it has earned.

It is worse in some conditions than others:

![](reports/figures/coverage_by_output.png)

The ranges get too tight as forecast output rises (left). They also get too tight as
the three weather models disagree more (right). The right-hand signal is the more useful
one: among hours whose ranges were equally wide, those with the most disagreement
missed by about twice as much. An earlier version of this chart grouped hours by
*actual* output, which exaggerates the high-wind shortfall: hours that turned out windy
are disproportionately the ones the forecast under-shot.

*Update 2026-09-22:* two calibration changes now ship (`reports/calibration.md`).
The first groups hours by model disagreement. The second fits the corrections on
out-of-sample predictions from the whole training window, not only its most recent
quarter, so an autumn forecast is no longer calibrated on summer residuals. Together
with the run-addressed weather data, coverage is **78%**, roughly even across seasons
and weather regimes, and the typical miss is down to 122 MW. The chart above shows the
current model.

The worst single day in the whole period, 13 February 2026, shows what this costs. The forecast
said around 1,800 MW; actual output was near 1,200 MW and fell to 500 MW. It was wrong by
about 520 MW for twenty-four hours straight, and the truth sat outside the stated range
in every hour but one. The forecast gave no warning at all: its range that day was no
wider than on any ordinary day. The model was not uncertain. It was confidently mistaken.

### 2. Half of each day is forecast from older weather data than it needs to be

![](reports/figures/nmae_by_lead.png)

Error is flat through the first half of the delivery day, jumps **35% in a single hour**,
then is flat again. That jump is not the weather getting harder to predict. It is an
artefact of how we obtain the weather data.

The weather archive we use can only be asked for values *as they stood a whole number of
days before the time being forecast* — one day before, two days before, and so on. It
cannot be asked for a specific weather model run.

We make our forecast at 10:00 market time for a day running 00:00 to 24:00 the next day.
So the earliest hours of that day are 14 hours ahead of us, and the latest are 38 hours
ahead. For the early hours, "as it stood one day earlier" is information that already
existed when we forecast — fine. For the later hours, "as it stood one day earlier" would
be information published *after* we made our forecast. We cannot use it without cheating,
so those hours have to fall back to two-days-earlier data instead.

The result is that the back half of every delivery day is forecast using weather
information a full day staler than the overnight run we actually had in hand. A
controlled test confirms this is the cause rather than time of day: deliberately feeding
the stale data to the *first* half of the day too makes its error jump by 45%, matching
the second half, while the second half does not move.

### 3. A basic sanity check on installed capacity does not pass

We express generation as a share of installed capacity, so we need to know how many
megawatts of turbines exist on any given date. The standard check is to look at the
highest output ever reached in a rolling window: if the capacity figure is right, the
fleet should occasionally come close to it, and that ratio should stay roughly flat over
the years.

![](reports/figures/ceiling_drift.png)

It does not. It falls steadily, from 0.91 in 2018 to 0.79 in 2025, and all four Swedish
zones fall together. Something is systematically off between reported generation and
reported capacity, and we do not yet know what. Two obvious explanations have been
tested and ruled out: it is not turbines being switched off when prices go negative, and
it is not the fleet spreading over a wider area. This matters because a drifting
denominator quietly distorts every percentage in this document.

Reconstructing the fleet turbine by turbine on ERA5 reanalysis holds the weather fixed and
narrows this down (`reports/era5_ceiling.md`). The turbines that existed in 2018 still
deliver what physics expects. Capacity added since then delivers only about 70% of its
expected output, every quarter, so the ratio falls as that capacity grows to half the
fleet. The same study shows that a model given the *actual* weather still misses by
112 MW on the backtest's hours, against 136 MW for the forecast, so better weather
data alone has limited headroom.

### 4. The market trades 15-minute blocks; this forecast is hourly

Since 1 December 2025 the Swedish bidding zones report generation in 15-minute periods,
following the move to 15-minute market settlement. This project averages that up to
hourly and forecasts hourly. That was the right simplification to start with, but it means the output is not
yet in the units the market actually trades.

---

## What comes next, in order

The full plan, with evidence for each item, is `docs/roadmap.md`. It was refined on
2026-09-21 from the literature review (`docs/literature.md`) and new diagnostics. Where
things stand:

1. **Run-addressed weather: done and shipped.** MET Norway MEPS (2.5 km) and ECMWF
   IFS HRES 00z runs now feed both the backtest and the daily forecast, which fetches
   and archives each day's runs (`configs/base.yaml: features.run_addressed`). On the
   same backtest rows they cut typical error by 12% and shrink the lead-34 step from
   +45% to about +20% (`reports/meps_archive.md`).
2. **Over-confidence (problem 1): largely fixed, and shipped.** Calibration is now
   grouped by weather-model disagreement and fitted on cross-fitted residuals: 80%
   coverage 0.74 → **0.78**, CRPS a further −3.7%, autumn 0.73 → 0.78
   (`reports/calibration.md`). The "worse at high wind" picture was partly an artefact
   of binning by actual output; the chart now bins by forecast.
3. **Watch the MEPS archive.** MET Norway's thredds archive now lists only the current
   month (checked 2026-09-22). The local copy of 735 runs cannot be re-downloaded, and
   the live model trains only on days with MEPS, so it currently stops at 2026-03-01
   until daily archiving fills the gap.
4. **Remaining bias by season** (winter over-, autumn under-prediction, about ±40 MW).
   Neither the day-of-year features nor calibration cause it; ERA5 shows it with the
   actual weather too, so it needs availability or outage data (roadmap C2/F).
5. Tried and not adopted: recent-error, negative-price and 18z lagged-run features
   (roadmap D1, D2, B5). The 18z jump is a strong uncertainty signal on rare hours and
   is a candidate calibration stratifier.
6. **Capacity drift (problem 3)**, **15-minute resolution**, then **German solar**.

Two deliberate omissions: a six-month slice of recent data (March–September 2026) has
been set aside untouched, to be used once for a final honest score, and no effort has
gone into tuning the model's settings, because with only two years of data that buys
flattering numbers rather than better forecasts.

---

## Reference

### Where the numbers come from

Every figure here is generated from the outputs of the backtest itself, so a chart
cannot drift away from the number it illustrates. Headline results cover **502 delivery
days, 12,026 hours**, between October 2024 and March 2026 (days that have every weather
source; before 2026-09-22 the board covered 546 days from September 2024) — see `docs/metrics.md` for
exactly which rows each statistic covers and what it measures.

| document | what it settles |
|---|---|
| `docs/metrics.md` | what every number means, and which days it covers |
| `docs/dataflow.md` | where the data comes from and what is known when |
| `reports/data_audit.md` | which data is trustworthy enough to model |
| `reports/protocol.md` | the scoring rules, frozen before any model was built |
| `reports/openmeteo_vintage.md` | the weather-data timing problem in detail |
| `reports/era5_ceiling.md` | how much the actual weather can explain, and the added-capacity shortfall |
| `reports/modelling.md` | full results, all metrics |
| `reports/meps_archive.md` | whether better weather data is obtainable |
| `docs/integration_contract.md` | how this would plug into `grid-signals` |

### Progress

| Phase | State |
|---|---|
| 1 — dataflow diagram + scaffold | done |
| 2 — data audit | done — GO for SE3 wind |
| 3 — targets, frozen scoring rules, baselines | done |
| 4 — weather feature pipeline | done |
| 5 — modelling | done |
| 6 — ensemble spike | done — run addressing yes, ensemble no |
| 6 — run-addressed NWP (MEPS + IFS runs) | backtested: −12% nMAE; live path next |
| 6 — calibration by NWP spread | done, shipped |
| 6 — German solar | not started |
| 7 — integration contract | drafted |
| 7 — live trial run | not started |

### Rules the code holds to

- **All times are stored in UTC.** Local market time appears only when defining which
  hours belong to a delivery day, and in the charts.
- **Nothing becomes an input unless it was knowable at 10:00 market time on the day the
  forecast is made.** Every input column records how old its information is, and a test
  fails the build if any of them is too fresh. This is the most important test here — it
  caught a real defect the first time it ran.
- **Never use a weather provider's automatic "best model" blend.** What it blends changes
  over time, which a model would learn as if it were weather.
- **Errors are measured against installed capacity, not average output**, so they stay
  comparable across years as the fleet grows.
- **Every number in a report comes from a function in `src/`**, so it can be re-derived.

### Layout

```
docs/      dataflow.md, metrics.md, integration_contract.md
configs/   base.yaml + experiments/ deep-merged on top
src/renewable_forecast/
  windows.py   issue times, delivery days, lead hours
  config.py    YAML load, deep merge, run fingerprint
  paths.py     every filesystem path, in one place
  store.py     parquet source of truth, DuckDB views over it
  sources/     ENTSO-E, Open-Meteo, the Swedish turbine registry
  targets/     what we are predicting, and the capacity denominator
  features/    weather to power conversion, and the design matrix
  evaluation/  splits, metrics, baselines
  models/      the forecasters themselves
  pipelines/   build, train, backtest, predict
  reporting/   every figure, generated from backtest outputs
notebooks/ exploration only -- may import from src/, never the reverse
tests/     time alignment, information-age guards, figure integrity
reports/   committed markdown + figures
data/      gitignored
mlruns/    gitignored (MLflow, SQLite backend)
```

### Running it

```bash
uv sync --group research
export PYTHONPATH=research/src

uv run python -m renewable_forecast.pipelines.data_audit   # data quality gate
uv run python -m renewable_forecast.pipelines.pull_meps    # MEPS archive backfill
uv run python -m renewable_forecast.pipelines.pull_ifs_runs  # IFS HRES 00z runs (--run-hour 18 for 18z)
uv run python -m renewable_forecast.pipelines.compare_meps --ifs      # run-addressed NWP A/B
uv run python -m renewable_forecast.pipelines.compare_calibration --schemes  # calibration A/B
uv run python -m renewable_forecast.pipelines.compare_blocks --help   # feature-block A/Bs
uv run python -m renewable_forecast.pipelines.train        # backtest + results
uv run python -m renewable_forecast.pipelines.predict      # forecast tomorrow; run after ~08:40 UTC,
                                                           # when the IFS 00z run is out
uv run python -m renewable_forecast.reporting.figures      # regenerate every figure
uv run mlflow ui --backend-store-uri sqlite:///research/mlruns/mlflow.db

uv run pytest research/tests
```

The research dependencies are an opt-in group, so a plain `uv sync` keeps the
`grid-signals` environment lean. `research/` shares the root `pyproject.toml` rather
than being an installed package, which is why `PYTHONPATH` is needed outside pytest.
