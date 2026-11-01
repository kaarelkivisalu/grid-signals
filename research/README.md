# Day-ahead power forecasting

Public market data and forecast weather become next-day generation and price
forecasts, with explicit information cutoffs, uncertainty and publication records.
The [project roadmap](../ROADMAP.md) sets current priorities: SE3-led demo delivery,
SE4 wind transfer, a bounded deep-learning comparison, then onshore wind, solar
and spot prices across all 15 Nordic/Baltic zones. German results remain supporting
case studies; the existing implementation does not yet provide regional coverage. The
[website](../README.md#run-the-local-demo) presents portable results.

The evidence table below records the October 15 research releases. Local
publication has since begun; see the [assessment](../docs/implementation-plan.md)
for the later trial observations. The [earlier research backlog](docs/roadmap.md)
is historical context, not a competing roadmap.

Reusable forecasting code now lives in the installed `grid_signals.forecast`
package. Focused experiments import that package; there is no checkout-only
`renewable_forecast` package or `PYTHONPATH` setup. Settings ship with the package,
while this directory retains reports, frozen protocols, model version records,
tests and local data. Prefect and saved trained models follow in milestone 2b.

## Current evidence — 2026-10-15

| Task | Evidence | Limit |
|---|---|---|
| SE3 wind | Final: 2.46% capacity-normalised MAE, 81.1% coverage at nominal 80%, 182/184 days | Hourly model repeated to quarter-hours; fleet availability remains approximate |
| DE-LU solar | Final: 2.84% daylight capacity-normalised MAE, 80.6% coverage, 184/184 days | Approximate fleet; mean overprediction of 2.07% capacity on daylight rows |
| DE-LU prices | Four fixed price-only references; 123 development days, 42/44 final holdout days | LEAR leads; uncertainty coverage deteriorates on holdout |
| DE-LU load | Four references; selected quantile GBM: 1,433 MW MAE vs 1,746 MW weekly naive, 79.7% 80% coverage, 44/44 final days | Actual-lag revisions assumed; six-site temperature approximation |
| Daily publication | Local timers installed; first scheduled issue October 16 | No completed on-time forward record yet |
| German wind, residual load, other zones | Planned | No complete custom German renewable chain or Europe-wide coverage claim |

Price results in EUR/MWh:

| Method | Development MAE | Final holdout MAE | Final 80% coverage |
|---|---|---|---|
| Hourly price-only LEAR | 24.72 | 37.21 | 68.2% |
| Native quarter-hour point GBM + residuals | 26.92 | 41.38 | 65.5% |
| Native quarter-hour direct quantile GBM | 26.16 | 42.97 | 52.9% |
| Weekly seasonal naive + residuals | 35.66 | 57.89 | 62.6% |

See [price development](reports/price_benchmark.md),
[final price evaluation](reports/price_holdout.md),
[price protocol](reports/price_protocol.md) and
[corrected renewable development](reports/products_15min.md).
The [final renewable evaluation](reports/holdout.md) compares fixed candidates with
physical and persistence references; its harness correction is recorded in the protocol.
The [monthly diagnostics](reports/holdout_diagnostics.md) report bias, coverage,
excluded dates and paired day-block confidence intervals against physical references.
Direct-quantile price GBM remains an experimental reference. LEAR is the newly
declared forward publication baseline, selected after the historical evaluations;
new forward issues assess that serving decision. No historical model was retuned.

Load evidence: [protocol](reports/load_protocol.md), [development](reports/load_benchmark.md),
[final evaluation](reports/load_holdout.md). The final load matrix is frozen and hashed.
An [out-of-sample load-input price experiment](reports/price_load_protocol.md) compares
price-only inputs with custom load medians and quantiles on matched development rows.
It requires separate forward confirmation; the completed price final window is not reopened.
The [first result](reports/price_load.md) changes MAE from 26.16 to 25.89 EUR/MWh
with the load median, but paired CRPS intervals include zero for both added-input
arms. This does not establish downstream value from the improved load forecast.

## Information and evaluation rules

- Cutoff: **09:00 UTC D-1**; publication deadline: 09:30 UTC. Creation and actual
  publication have separate timestamps. Only immutable first on-time issues enter
  live scoring; late, early, retrospective, legacy and revised forecasts are excluded.
- Use run-addressed weather where available, train-only preprocessing/calibration,
  rolling refits, a seven-day embargo and matched complete delivery days.
- Renewable errors use installed-capacity normalisation; solar headline metrics
  exclude night. Prices use EUR/MWh, retain negative values and avoid MAPE.
- Historical hourly prices are not native quarter-hour GBM targets. The price GBMs
  use the genuine SDAC quarter-hour regime from October 2025.
- ENTSO-E A69/A01's reference is fixed at 18:00 Brussels time. Its historical API
  response alone does not establish availability at our cutoff. Exceptional apparent
  accuracy does not prove a particular revision mechanism.
- Save public forecasts with raw XML, request/receipt timestamps, metadata and
  hashes. Retain missing and late responses. Historical public fundamentals are
  excluded from price modelling until evidence that the data was available before the cutoff is verified.
- Residual-load uncertainty needs a joint distribution, not marginal subtraction.

The renewable final window is March 20–September 19, 2026; the separate price final
window is September 1–October 14. Model version records with source/settings checksums are in
`configs/releases/`; local data and publication evidence remain gitignored.
Older September hourly charts predate the corrected weather-age policy and are
archival evidence, not current accuracy claims.

## Run the research

```bash
uv sync --frozen --group research
uv run grid-signals info
uv run grid-signals workflow capture
uv run grid-signals workflow forecast
uv run grid-signals workflow score
uv run grid-signals fetch-price 2026-10-01 2026-10-15
uv run grid-signals fetch-load 2026-10-01 2026-10-15
uv run grid-signals backtest-price
uv run grid-signals backtest-load
uv run grid-signals forecast --product de-price
uv run grid-signals forecast --product de-load
uv run grid-signals experiment decision_study
uv run grid-signals backtest --fuel wind_onshore
uv run grid-signals backtest --fuel solar
uv run grid-signals export all
uv run pytest research/tests
```

Use `workflow forecast --no-refresh` only with required source data already cached.
It preserves real publication timing. `workflow` retains the existing local trial
behaviour until 2b; individual product operations use the same installed package.
See [operations](../docs/operations.md) for configuration, timers and preservation.
No scheduled job reopens a holdout.

Original release records in `research/configs/releases` retain their original
source paths and hashes. Exact reruns of those evaluations, including the locked
price/load experiment, use the preserved original checkout and datasets described
in operations. They are not silently reidentified as evaluations of moved code.
The new `consolidated_v1.json` record identifies the installed package separately;
fixed-input prediction and metric checks establish migration equivalence.
Old report reproduction blocks describe the original checkout. Current commands
above are the supported operating interface.

The exploratory decision example shifts 1 MWh/day into eight quarter-hours under a
0.5 MW limit. It uses development predictions, allows interruptions and excludes
fees, taxes and grid charges. Weekly persistence captures most of the benefit
versus uniform consumption; this is not a trading-profit claim.

## Package map and background

`sources/` acquires data; `targets/` defines actuals and capacity; `features/`
assembles eligible inputs; `models/` holds predictors; `evaluation/` defines
splits and scores; `pipelines/` runs evaluation/publication; `reporting/` exports
results. Parquet datasets and MLflow runs remain local and gitignored.

Further context: [dataflow](docs/dataflow.md), [metrics](docs/metrics.md),
[literature](docs/literature.md), [renewable final protocol](reports/holdout_protocol.md),
[integration contract](docs/integration_contract.md),
[public forecast inventory](../src/grid_signals/forecast/configs/benchmarks.yaml).
