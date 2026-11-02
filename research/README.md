# Research evidence

This directory holds evaluation reports, frozen protocols, model version records
and local research data. Reusable code lives in `grid_signals.forecast`.
Start with the [model reference](../docs/dataflow.md) for current inputs and model
choices; use the [roadmap](../ROADMAP.md) for priorities.

## Results from the October 15, 2026 evaluations

| Task | Main result | Important limit | Evidence |
|---|---|---|---|
| SE3 wind | 2.46% capacity-normalised MAE; 81.1% coverage for the nominal 80% range; 182/184 days | Hourly-trained forecast repeated to quarter-hours; approximate fleet availability | [Protocol](reports/holdout_protocol.md), [results](reports/holdout.md), [diagnostics](reports/holdout_diagnostics.md) |
| DE-LU solar | 2.84% daylight capacity-normalised MAE; 80.6% coverage; 184/184 days | Approximate fleet; daylight overprediction of 2.07% capacity | [Development](reports/products_15min.md), [final results](reports/holdout.md) |
| DE-LU load | Selected quantile GBM: 1,433 MW MAE versus 1,746 MW weekly reference; 79.7% coverage; 44/44 days | Assumed actual-lag revisions; six-site temperature approximation | [Protocol](reports/load_protocol.md), [development](reports/load_benchmark.md), [final results](reports/load_holdout.md) |
| DE-LU prices | LEAR: 37.21 EUR/MWh final MAE versus 57.89 weekly reference; 68.2% coverage; 42/44 days | Price intervals under-cover; LEAR's forward selection followed historical evaluation | [Protocol](reports/price_protocol.md), [development](reports/price_benchmark.md), [final results](reports/price_holdout.md) |
| Custom load as price input | MAE changed from 26.16 to 25.89 EUR/MWh with the load median | Paired CRPS intervals include zero; no resolved gain | [Protocol](reports/price_load_protocol.md), [result](reports/price_load.md) |

Renewable final delivery dates are March 20–September 19, 2026; load/price final
windows are September 1–October 14. Reports retain scored populations, exclusions
and original reproduction commands. See [metrics](../docs/metrics.md) before
comparing scores across evaluations.

The SE3 daily saved-model policy is a separate forward version. Reload and
migration checks establish implementation equivalence, not independently measured
live skill. Its deployment and reliability status are in the roadmap.

## Reproduce or extend the work

For exact frozen evaluations, use the original source, locked environment and
cached data in the [preservation record](../docs/archive/operations-record.md#preservation-and-source-consolidation--2026-11-01).
Original records in `research/configs/releases/` retain their source paths and
hashes. Old report commands target that checkout. The consolidated package and
saved-model runtime have separate records under
`src/grid_signals/forecast/configs/releases/`; do not rewrite old identities.

For current development comparisons, follow the
[research commands](../docs/operations.md#run-development-comparisons). New model
selection must use a declared development protocol; completed final windows stay
closed to tuning. Local raw data, frozen load matrices, price caches and MLflow
runs are gitignored. Website bundles contain results, not training inputs.

## Supporting studies

- [Data audit](reports/data_audit.md) and [original evaluation protocol](reports/protocol.md).
- [Weather information age](reports/openmeteo_vintage.md),
  [MEPS/IFS comparisons](reports/meps_archive.md), [calibration](reports/calibration.md)
  and [original modelling](reports/modelling.md). Earlier hourly boards predate
  corrected weather timing; they are historical evidence.
- [ERA5 ceiling](reports/era5_ceiling.md) and [generated tables](reports/era5_ceiling_tables.md).
- [Literature library](literature.md), [historical research backlog](../docs/archive/research-roadmap.md)
  and [dated market notes](../docs/archive/MARKET_CHANGES.md).

Literal `docs/...` references inside original reports and source comments may refer to the former
`research/docs/` directory. Current model/metric/publication guides are in
`../docs/`; the old hourly metric guide and research backlog are in `../docs/archive/`.
