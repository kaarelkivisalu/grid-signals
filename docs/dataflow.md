# Model reference: sources, features and choices

Reviewed against the implementation on **2026-11-02**. Use this reference to
trace each model from provider inputs through features, fitting and prediction.
For scores, start with [research evidence](../research/README.md); for commands,
use [operations](operations.md). The [roadmap](../ROADMAP.md) owns operating status.

The common pattern is market observations + eligible forecast weather → derived
features → quantile model and references → saved forecasts. The website reads
results; it does not run models. SE3 uses a saved-model lifecycle; German products
remain manually runnable case studies.

## 1. Which models are in scope?

| Product | Selected model | Supporting reference | Operating status |
|---|---|---|---|
| SE3 onshore wind | `QuantileGBM`, served as `hourly_repeated`; saved-model policy `se3-wind-saved-v1-daily-before-issue` | Fitted `PhysicalPowerCurve`; eligible captured public wind point forecast | The only product scheduled by the new Prefect stack; implementation verified locally, owner deployment/cutover pending |
| DE-LU solar | `SolarQuantileGBM`, native quarter-hour | Historical `SolarPhysical` and `SmartPersistence` | Saved website case study and manual `forecast --product de-solar`; no new production schedule |
| DE-LU load | Development-selected `load_quantile_gbm` / `QuantileLoad` | Historical `load_weekly`, ridge and point GBM comparisons | Saved website case study and manual `forecast --product de-load`; no new production schedule |
| DE-LU prices | `lear_hourly` / `ResidualDistribution(Lear)` for forward publication | Historical weekly naive and price GBM comparisons | Saved website case study and manual `forecast --product de-price`; no new production schedule |

A product's presence in [products.py](../src/grid_signals/products.py) does not
mean it has a deployed schedule. Website alternatives are archived comparisons,
not extra models run on every visit. SE3's physical reference is prepared and
predicted alongside its main model. The public wind forecast is fetched as a
comparison, not trained here and not used as a feature. German physical/persistence
references are evaluation models, not extra outputs of their manual forecast commands.

No neural network, LLM, ERA5-based model, Schaake scenario generator, price model
with custom-load inputs, offshore model or model for another Nordic/Baltic zone is
in the new serving workflow. Their research code or plans do not imply deployment.
The old local multi-product timers use preserved 2a source until owner cutover;
their schedule is documented separately in operations.

### Find model details

| Question | Where to read |
|---|---|
| Exact providers, requested fields, fetching and caveats | [Wind](#31-source-data-exact-use-and-fetching), [solar](#41-sources-and-fetching), [load](#51-sources-and-fetching), [prices](#61-source-and-fetching) |
| Exact derived inputs | [Wind](#32-exact-derived-features), [solar](#42-features-and-physical-conversion), [load](#52-features), [prices](#62-features) |
| Architecture and fitted parameters | [Wind](#33-architecture-training-and-promotion), [solar](#43-architecture-rationale-and-references), [load](#53-architecture-and-choice), [prices](#63-architecture-and-selection) |
| Why these choices | Model-specific rationale below; [evidence limits](#7-evaluation-evidence-and-limits) |
| Backtest protocols and results | [Research evidence](../research/README.md) |
| Host, services, schedules, storage and failure/recovery | [Architecture](implementation-plan.md), [operations](operations.md) |

All source links below refer to the current installed package. Exact reproduction
of frozen evaluations uses the preserved original source/environment and inputs,
as explained in [operations](operations.md#preservation-and-source-consolidation--2026-11-01).

## 2. Shared task and data conventions

Let **I** be the issue day and **D = I + 1** the delivery day. The information cutoff
is **09:00 UTC on I**, with a **09:30 UTC** publication deadline. A forecast's
intended cutoff, actual computation time and actual delivery time are separate.
UTC timestamps identify intervals; delivery days follow CET/CEST. The current
[windows.py](../src/grid_signals/forecast/windows.py) uses `Europe/Stockholm`,
which has the same clock transitions as these SE3/DE-LU tasks. The product registry
records `Europe/Berlin` for the evaluated products. Neither is a generic contract
for every future zone.

There are 92, 96 or 100 quarter-hours per delivery day. SE3 wind and forward LEAR
prices repeat an hourly distribution across its quarter-hours. Solar and load
train on native quarter-hour targets. Repetition/interpolation never establishes
native sub-hourly weather skill. Values in MW are interval-average power, not MWh.

Every selected model produces 19 marginal quantiles, q0.05 through q0.95 in 0.05
steps. q0.50 is the point forecast; q0.10–q0.90 is the nominal 80% range. These
quantiles are not joint scenarios and must not be added/subtracted as if they were.
Wind/solar learn capacity factor (CF = generation MW / capacity MW), then scale to
MW. Load learns MW; prices learn EUR/MWh and retain negative values.

Missing source data remain missing. SE3 checks complete forecast grids and finite
predictions before publication; scoring comparisons use matched complete days. Some
nonessential features can be NaN and are handled by LightGBM. Required weather
checks are not a guarantee that every feature or every source grid cell is complete.

## 3. SE3 wind and its physical reference

### 3.1 Source data, exact use and fetching

| Source and code | Exact data used | Fetching and important limits |
|---|---|---|
| ENTSO-E actual generation, [observations.refresh](../src/grid_signals/forecast/sources/observations.py), [entsoe.load](../src/grid_signals/forecast/sources/entsoe.py), [actuals.py](../src/grid_signals/forecast/targets/actuals.py) | A75 generation for `SE_3`; select `wind_onshore` / B19 and the actual generation aggregation, excluding consumption rows. Hourly means supply training CF and 48/72/168-hour generation lags; genuine quarter-hours supply current forward scores. | At preparation and scoring, `EntsoeRawClient` requests local-midnight bounds from I−7 through I+1 exclusive. Each refresh saves a uniquely dated raw XML, parsed Parquet and receipt/hash. The loader resolves overlaps by retrieval time. Actuals can be revised; historical lag values are not proven original issue-time vintages. Older hourly data are not expanded into genuine quarter-hour scoring targets. |
| Vindbrukskollen, [fleet.py](../src/grid_signals/forecast/sources/fleet.py), [sites.build](../src/grid_signals/forecast/features/sites.py), committed [zone polygons](../src/grid_signals/forecast/configs/se_bidding_zones.geojson) | Local GeoPackage `raw/vindbrukskollen/lst.vbk_vindkraftverk.gpkg`: `VERKID`, `OMRID`, geometry, `MAXEFFEKT`, `UPPFORT`, `STATUS`, `NAVHOJD`, `ROTDIAMETER`, `FABRIKAT`, `MODELL`, `PLACERING`, `LANSNAMN`, `SenasteUppdatering`. Positions, rated MW, commissioning/decommissioning information determine the zone capacity series; active SE3 onshore coordinates, capacities and mean hub heights define eight weather query clusters. Other retained attributes are not all ML features. | The GeoPackage is a seeded/manual input: daily flows **do not download a new registry**. The download URL and missing-file error are in `fleet.py`. Zone assignment uses a spatial join and nearest-zone fallback for unmatched coastal points. A current registry reconstructs historical commissioning; decommissioning uses the last-update date as a proxy. This is not a fully versioned historical fleet. Archive any proposed replacement before changing the saved-model inputs. |
| ENTSO-E A68 national installed capacity | Cached Sweden-wide capacity is an audit cross-check, not the numeric SE3 prediction denominator or an ML input. | The original data audit compared national registry totals with A68. No daily A68 refresh or national rescaling is performed by the SE3 flow. Zonal CF uses the registry capacity series. See [data audit](../research/reports/data_audit.md) and [labels.build](../src/grid_signals/forecast/targets/labels.py). |
| Open-Meteo Previous Runs, [openmeteo.py](../src/grid_signals/forecast/sources/openmeteo.py) | Pinned `ecmwf_ifs025`, `gfs025`, `icon_eu` at the eight SE3 clusters. Requested hourly fields: `wind_speed_100m`, `wind_speed_10m`, `wind_direction_100m`, `wind_gusts_10m`, `temperature_2m`, `relative_humidity_2m`, `surface_pressure`, `snow_depth`, `precipitation`, each at `_previous_day1` and `_previous_day2`. Wind is requested in m/s, timestamps in UTC. Precipitation is fetched but not used in the selected feature matrix. | Both preparation and prediction call the shared puller; exact ranges are in [operations](operations.md). Parameter-hashed JSON gzip cache, serial point/model requests, parsed point/model Parquets merged by valid time. Offsets mean values predicted 24/48 hours before valid time, **not a named 00z run**. Per-row offset selection includes forward-trajectory endpoints. No `best_match` blend. Measured archive starts in code are February/March 2024, not a promise about future provider coverage. |
| MET Norway THREDDS MEPS, [meps.py](../src/grid_signals/forecast/sources/meps.py) | Deterministic `meps_det_hl`, named 00z issue-day run; `x_wind_z`, `y_wind_z`, `air_temperature_z`, `relative_humidity_z` at 80 and 120 m; hourly leads 16…50. Nearest cells for the eight clusters are extracted from one OPeNDAP bounding box (`radius=0`; neighbourhood averaging is not enabled). | Serial xarray/netCDF OPeNDAP access, parsed per-run Parquet storage. The downloaded bounding box/raw binary is **not retained** by this path. Grid-relative wind is rotated to Earth-relative direction; kelvin temperature and fractional humidity are converted. Uses fixed, tested 2.5 km grid geometry. This is **not the 30-member MEPS ensemble**. Its product was chosen for the stable archived signature. The provenance guard stamps the run instant; actual service availability is an operational assumption, not an archived receipt-time proof. |
| Open-Meteo Single Runs IFS, [ifs_runs.py](../src/grid_signals/forecast/sources/ifs_runs.py) | `models=ecmwf_ifs` (HRES, distinct from `ecmwf_ifs025`), `run=I T00:00`. The same nine weather variables as above under plain names, eight coordinates in one request. `forecast_hours=54`, with the first 16 hours discarded for the 00z block. | Parameter-hashed JSON gzip plus parsed per-run Parquet. Columns are dated to run time + **8 h 35 min** by the guard; this is the fixed conservative assumption from the recorded latency study, not measured Open-Meteo receipt time for every historical run. The 18z cycle and jump features exist in research code but are disabled in the serving configuration. |
| ENTSO-E public wind forecast, [capture.run](../src/grid_signals/forecast/sources/capture.py), [captured_curve](../src/grid_signals/forecast/live.py) | A69 with **process A18** for SE3's next delivery day. Select the complete onshore wind curve. Retain raw XML, parsed Parquet, request/receipt times, document creation/revision fields and hashes. | Scheduled 08:55 UTC. Only a complete response received by 09:00 is eligible. Native quarter-hours or explicitly repeated hourly points can be compared. This is a point-error comparison, not a probabilistic forecast model fitted here. Historical A69/**A01** latest-vintage boards are a different, optimistic comparison; do not substitute them for the captured curve. |

The active fleet is clustered with capacity-weighted KMeans, eight clusters,
`random_state=0`, `n_init=10`, in EPSG:3006 before centroids return to WGS84.
Weights are cluster rated MW / total rated MW; cluster hub height is the arithmetic
mean of its turbines' reported heights. Eight points are an explicit API-cost and
spatial-detail compromise, **not an optimum established by a cluster-count ablation**.
The cluster fleet uses currently non-decommissioned turbines, so historical weather
sampling is not a fully reconstructed as-of fleet.

Default endpoints are `https://web-api.tp.entsoe.eu/api`,
`https://previous-runs-api.open-meteo.com/v1/forecast`,
`https://single-runs-api.open-meteo.com/v1/forecast`, and the `DODS_ROOT` / dated
`run_url` in `sources/meps.py`. ENTSO-E needs `ENTSOE_API_KEY`; the weather pullers
use the public endpoints without a key. The registry is read from disk. Weather
units are m/s, °C, relative humidity percent, hPa and snow depth metres after
source normalisation; fetched precipitation is in mm but not selected. Solar
irradiance is W/m². Exact request dictionaries and retry/cache behaviour are in
the linked `pull`, `params_for`, `fetch`, `refresh` and `fetch_run` functions.

These weather inputs are provider-run numerical weather prediction products:
ECMWF IFS, NOAA GFS, DWD ICON-EU and MET Norway MEPS. This repository does not train
those atmospheric models. Pinning API product names and run times prevents an
automatic provider blend, but does not freeze every upstream model upgrade or
archive correction. A stable file signature is not proof of unchanged NWP physics.

[labels.build](../src/grid_signals/forecast/targets/labels.py) drops partial hours
and marks CF in −0.01…1.05 as trainable. Capacity disagreement/quarantine and
nonpositive-price curtailment flags are diagnostics; they do not themselves remove
rows from training. Cached SE3 prices can create those flags but are **not inputs**
to the selected wind model. `attach_prices` and `attach_residuals` are optional
research feature builders and are not called by the serving assembly.

### 3.2 Exact derived features

Authoritative construction: [wind.py](../src/grid_signals/forecast/features/wind.py),
[assemble.py](../src/grid_signals/forecast/features/assemble.py). Selection:
[models.base.feature_columns](../src/grid_signals/forecast/models/base.py) takes
numeric columns except its explicit `EXCLUDED` set. Capacity, targets, dates,
source run times and `nwp_offset_days` are bookkeeping, not learned inputs.

The default retained validation matrix has **155 features**, specified below by
exact naming rules. The fitted model's own `columns` list is authoritative for a
particular artifact; additional research columns are not implied by this list.

To inspect a trusted saved artifact without fitting or contacting a provider,
replace `/path/to/model` with its directory under the configured model root:

```bash
uv run python - <<'PY'
from pathlib import Path
import pandas as pd
from grid_signals.forecast.models.base import feature_columns
directory = Path("/path/to/model")
training = pd.read_parquet(directory / "training.parquet")
inputs = pd.read_parquet(directory / "reload_inputs.parquet")
print("Feature order:", feature_columns(training))
print("Retained probe values:")
print(inputs[feature_columns(training)].to_string(index=False))
print((directory / "record.json").read_text())
PY
```

The fitted `model.columns` uses that selector and order. Per-issue
`inputs.parquet` retains the actual future feature rows, distinct from the reload
probe; read it with the same columns to inspect a particular issued forecast.

| Block | Exact names or name expansion | Transformation / role |
|---|---|---|
| Basic (8) | `lead_hour`, `cf_lag_48`, `cf_lag_72`, `cf_lag_168`, `hour_sin`, `hour_cos`, `doy_sin`, `doy_cos` | Lead from the issue-day 00z reference; hourly CF at the three UTC lags; local-clock 24-hour and day-of-year / 365.25 sine/cosine cycles. |
| Previous Runs per-model (57) | Each stem below followed by `__ecmwf_ifs025`, `__gfs025`, `__icon_eu` | Compute physics per cluster before aggregating, separately for each provider model. |
| Previous Runs disagreement (6) | `{power_curve,wind_speed_100m}_model_{mean,std,range}` | Mean, population standard deviation and range across provider-model zonal values. This is deterministic model disagreement, not an ensemble-member distribution. |
| Previous Runs trajectory (16) | Apply the eight trajectory suffixes below to `power_curve_model_mean` and `wind_speed_100m_model_mean` | Weather path around the target hour. |
| MEPS physical/spatial (16) | Stems listed below followed by `__meps` | Height-specific physics, cluster aggregation and spatial variation. |
| MEPS trajectory (16) | Eight trajectory suffixes on `power_curve__meps`, `wind_speed_hub__meps` | Calculated within each run, never across cycles. |
| IFS run physical/spatial (18) | The Previous Runs stems except `lead_spread`, followed by `__ifsrun` | Same physical functions with the named IFS run. |
| IFS run trajectory (16) | Eight trajectory suffixes on `power_curve__ifsrun`, `wind_speed_100m__ifsrun` | Calculated within each run. |
| Run-source disagreement (2) | `power_curve_runs_mean__meps__ifsrun`, `power_curve_runs_std__meps__ifsrun` | Mean and population standard deviation between MEPS and IFS physical output. |

Previous Runs stems (19):

```text
wind_speed_100m, power_curve, air_density, speed_cubed, shear_ratio,
gust_factor, direction_sin, direction_cos, temperature_2m, snow_depth,
icing_now, lead_spread, icing_6h, icing_12h, icing_24h,
wind_speed_100m_spatial_std, wind_speed_100m_spatial_range,
power_curve_spatial_std, power_curve_spatial_range
```

MEPS stems (16):

```text
wind_speed_hub, power_curve, air_density, speed_cubed, shear_exponent,
direction_sin, direction_cos, temperature_hub, icing_now,
icing_6h, icing_12h, icing_24h,
wind_speed_hub_spatial_std, wind_speed_hub_spatial_range,
power_curve_spatial_std, power_curve_spatial_range
```

Eight trajectory suffixes:

```text
_shift-3, _shift-1, _shift+1, _shift+3,
_ramp1, _ramp3, _roll6_mean, _roll6_std
```

`shift-3`/`shift-1` read **future forecast values** three/one hours later;
positive shifts read earlier values. Ramps subtract the value one/three hours
before; rolling statistics use six trailing hourly samples. The safe Previous
Runs offset uses `ceil(valid_time to hour) + 3 h`, not just the target timestamp,
so forecast lookahead does not introduce newer information.

The physical formulas and assumptions are explicit in `wind.py`:

- Moist-air density uses temperature, pressure and humidity. Correct wind speed by
  `(density / 1.225)^(1/3)` before the generic IEC class-II power-curve interpolation;
  `speed_cubed` is that corrected speed cubed. Previous Runs/IFS use 100 m wind
  directly; their learned physical feature is not individually extrapolated to
  every turbine's hub height.
- `shear_ratio` is 100 m / 10 m speed; `gust_factor` is 10 m gust / 10 m speed,
  with a fallback ratio of one for near-calm denominators. Directions use sine/cosine.
- MEPS derives a shear exponent from 80/120 m speed, clips it to −0.2…0.8,
  extrapolates/interpolates speed to the cluster mean hub height, and interpolates
  vector direction, temperature and humidity. Pressure is fixed at 1013.25 hPa.
- Icing is temperature < 1°C and relative humidity > 95%; 6/12/24-hour rolling
  counts retain persistence. These are proxy features, not observed turbine icing.
- Means are capacity-weighted over available finite cluster values. Spatial std
  and range are unweighted across clusters. Some missing clusters can therefore
  be absorbed by the weighted-mean calculation; the required-source checks do not
  certify complete coverage of every cluster.
- `lead_spread` is absolute 100 m wind difference between the chosen whole-day
  offset and the next staler offset. The default fetcher requests only offsets 1
  and 2. Despite a `SPREAD_ONLY_OFFSET = 3` constant, it does **not** request offset
  3 automatically. Consequently offset-2 rows can lack this feature; LightGBM sees
  NaN. Do not describe offset 3 as a guaranteed production input.

The physical comparison model uses only **`power_curve_model_mean`** from the
Previous Runs providers as its predictive feature. It does not directly use the
additional MEPS/IFS blocks or learned CF lags, although the workflow requires
those blocks for the main model and evaluates both on identical rows.

### 3.3 Architecture, training and promotion

[QuantileGBM](../src/grid_signals/forecast/models/quantile.py) is 19 independent
LightGBM gradient-boosted tree regressors with quantile/pinball loss, one per
level. Defaults: 400 trees, 31 leaves, learning rate 0.05, minimum child samples
40, row fraction 0.8 with frequency 1, column fraction 0.8, L2 penalty 1.0. Serving
sets four threads. These are fixed modest tabular-model settings, not evidence of
an exhaustive hyperparameter search. Quantile boosters have no monotone constraints.

Raw quantiles are clipped to [0,1] and sorted. Four contiguous whole-day blocks
within the available training window produce out-of-fold predictions (fit each
block's complement); final boosters are then refitted on all training rows.
[SpreadCQR](../src/grid_signals/forecast/models/conformal.py) applies additive
residual corrections by predicted CF bin (four bins) and weather-spread tercile
(`power_curve_model_std`), falling back to level then global corrections below
30 rows. `normalise=False`, `by_season=False`. This is training-side block crossfit,
not a chronological outer test; all these blocks precede the forecast issue.
The online `adaptive_levels` helper is **not called** by the serving flow.
Time-series dependence prevents an unconditional conformal coverage guarantee.

[PhysicalPowerCurve](../src/grid_signals/forecast/evaluation/baselines.py) fits
an affine scale/intercept to the physical feature on the older 75% of training
days. The newest 25% supplies empirical residual quantiles. Its point and final
quantiles are bounded to [0,1]. It is a calibrated physical reference, not a wholly
unfitted power curve.

[saved_models.prepare](../src/grid_signals/forecast/saved_models.py) uses all
available eligible hourly rows on delivery days strictly before
`min(issue_day, preparation_UTC_date)`. It requires at least 60 distinct training
days, rejects a last training day over three days behind the issue and excludes
whole assembled days with missing configured run-source output. This is a daily
expanding-history policy, **not the monthly seven-day-embargo backtest refit rule**.
The actual rows/counts and lag-history snapshot are saved; do not infer a complete
training-day grid merely from the minimum distinct-day count.

Training saves both models, exact training and lag data, a reload probe and its
predictions, settings, source hashes and dependency versions. A checked reload
must agree within the implemented `1e-12` tolerances before promotion. Each model
has an immutable record and explicit promotion reason/history. Loading rejects
changed files/code/environment, a different issue, preparation after the cutoff,
future preparation times and age over 30 hours. No fallback training occurs in
prediction. See `prepare`, `validate`, `promote`, `load` and
[live.candidate](../src/grid_signals/forecast/live.py).

### 3.4 Why this combination?

Physics supplies the nonlinear wind-to-power response and aggregation before
learning; the GBM corrects remaining weather/fleet relationships and estimates
conditional quantiles without assuming a Gaussian distribution. Safe generation
lags represent persistent fleet/output regimes; cycles represent season/time of
day; spread, trajectory and icing terms represent uncertainty, ramps and weather
regimes. Those are physical/statistical motivations, not proof that every column
has a separately measured marginal benefit.

Recorded choices have different strengths of evidence:

- Adding MEPS and named IFS runs to the Previous Runs block improved matched
  development errors; keeping all sources beat replacing the old block entirely.
  See [MEPS/IFS comparisons](../research/reports/meps_archive.md).
- Crossfit/additive spread calibration was selected using the development
  comparisons in [calibration.md](../research/reports/calibration.md). Seasonal strata and
  width-normalised correction did not earn adoption.
- Hourly repetition remained the serving default because quarter-hour weather
  interpolation did not establish a CRPS gain on its matched winter A/B.
- Eight clusters, the generic curve, individual weather terms and model parameter
  values include explicit engineering choices. No exhaustive source/feature
  subset search or per-feature causal attribution is recorded. Feature importance
  is descriptive, not an ablation.

These decisions support a new forward trial, not a claim that the daily saved-model
policy has already achieved the historical final scores. Exact results are in section 7.

## 4. DE-LU solar

### 4.1 Sources and fetching

[solar.build/refresh](../src/grid_signals/forecast/features/solar.py) and
[delu_solar.yaml](../src/grid_signals/forecast/configs/experiments/delu_solar.yaml)
use ENTSO-E A75 B16 solar generation for DE-LU, A68 solar annual capacity and
Open-Meteo **`ecmwf_ifs025` only**. Weather requests contain
`shortwave_radiation_instant`, `temperature_2m`, `snow_depth` at offsets 1 and 2.
Instantaneous radiation avoids treating a backward-hour average as an instantaneous
sample. Missing regional radiation stays missing rather than becoming zero.

The six equal-weight points are in
[solar_sites.csv](../src/grid_signals/forecast/configs/solar_sites.csv): the
Cartesian product of latitudes 48.5, 51.0, 53.5 and longitudes 8.0, 12.5; each has
weight 1/6. These are a declared lattice, **not MaStR registry or capacity weights**.
A68 capacity uses the last annual snapshot at/before issue; duplicate snapshot
timestamps take the largest value. Original publication-time vintages of those
annual snapshots are not available, so this as-of timestamp rule is an assumption.

A manual `forecast --product de-solar` refreshes those weather fields over
[D−1, D+2), merges them into the cache, then fits and predicts. It does **not**
automatically refresh A75/A68 or build a dated PV fleet. Seed those histories;
`fetch-actuals START END` fetches SE3 and DE-LU generation, and the generic ENTSO-E
cache skips an identical already-cached chunk. Capacity fetching is part of the
explicit data setup, not a daily German job. See `sources.entsoe.backfill` and
[pull_solar.py](../src/grid_signals/forecast/pipelines/pull_solar.py).

### 4.2 Features and physical conversion

There are **11** selected numeric features:

```text
physical_cf, clear_sky_cf, ghi, temperature_2m, snow_flag,
solar_elevation, lead_hour, hour_sin, hour_cos, doy_sin, doy_cos
```

Hourly GHI / calculated clear-sky GHI gives clear-sky index, interpolated at
quarter-hour **midpoints**, bounded to 0…1.5 and multiplied by midpoint clear sky.
Both hourly endpoints must satisfy the issue-time age rule. Temperature and snow
are interpolated too. [pv_output](../src/grid_signals/forecast/features/solar.py)
uses pvlib solar position, Erbs direct/diffuse decomposition, plane-of-array
irradiance and PVWatts DC. Fixed mix: 50% south (tilt 30°, azimuth 180°), 25% east
(20°, 90°), 25% west (20°, 270°). Cell temperature is ambient + 0.03 × plane irradiance;
temperature coefficient −0.004/°C; output loss factor 0.86. These are nominal fleet
assumptions. `clear_sky_cf` uses clear-sky irradiance and 20°C ambient. Site outputs
and weather are weighted 1/6; elevation is the maximum across sites; snow flag is
the weighted share with snow depth > 0.01 m. No generation lags enter the main model.

### 4.3 Architecture, rationale and references

[SolarQuantileGBM](../src/grid_signals/forecast/models/solar.py) wraps the same
19-quantile LightGBM and four-block crossfit calibration as wind, with the
configuration override above. It trains on elevation > 0° with valid target and
physical output, requiring at least 30 daylight training days. It sets all night
quantiles to zero. Evaluation headlines instead use elevation > **5°**, excluding
near-horizon periods. Solar lacks `power_curve_model_std`; the shared calibrator's
spread input defaults to zero, so its meaningful strata are predicted level,
with the usual sparse/global fallback. It does not gain wind-model disagreement
merely by sharing a class.

Manual publication fits on all available solar training rows with delivery day
< issue day, then predicts natively at quarter-hours; it has no saved-model
promotion policy in 2b. `operations.forecast` calls `predict.run` / `_fit_forecast`.

Physics/solar geometry handles dawn, dusk and the nonlinear irradiance-to-output
chain; the statistical correction learns systematic residual effects. The
six-point lattice and orientation/loss assumptions are bounded initial choices,
not outcomes of a fleet/orientation optimisation. The winter A/B and final
holdout supported the quantile model over the physical/persistence references;
section 7 gives their actual populations and coverage.

Historical reference implementations are in
[evaluation/solar.py](../src/grid_signals/forecast/evaluation/solar.py):
`SolarPhysical` fits one derating factor and held-out, clear-sky-scaled residual
quantiles; `SmartPersistence` uses observed CF / clear-sky CF at a **48-hour UTC lag**
with a training-median fallback and residual uncertainty. They test added value
beyond physics and recent sky conditions. `ClearSkyClimatology` is a development-only
reference. None establishes a registry-weighted PV forecast or resolves sub-hourly clouds.

## 5. DE-LU load

### 5.1 Sources and fetching

Policy: [load.yaml](../src/grid_signals/forecast/configs/load.yaml).
[observations.fetch/load](../src/grid_signals/forecast/sources/load.py) calls
ENTSO-E `query_load("DE_LU")`, A65 / process A16. The target is actual total load
including losses and excluding absorbed storage energy; it is not the public
load forecast. Store parsed quarter-hour MW and `fetched_at`, resolve overlaps
by newest retrieval, reject nonpositive actuals, and never forward-fill missing
targets. This older source saves parsed responses, not the new SE3 raw-XML receipt
scheme. Historical revised lags remain an explicit assumption.

Weather is the same six-point equal-area lattice and `ecmwf_ifs025`
`temperature_2m_previous_day{1,2}` archive used by solar, not observed temperature.
Interpolate to interval midpoints using the smallest safe offset for the following
hour endpoint. The shared `pull_solar` weather command supplies these fields.
No dedicated German weather refresh schedule exists.

Manual `forecast --product de-load` refreshes actual load over [D−8, D+1) with
`refresh=True`, but does **not** fetch temperature. Historical data and eligible
future temperatures must already be cached. `fetch-load START END` supports setup;
the historical bulk pull skips existing chunks, whereas the explicit manual
forecast refresh replaces the requested load chunk. References: [operations.py](../src/grid_signals/forecast/operations.py),
[features/load.py](../src/grid_signals/forecast/features/load.py).

### 5.2 Features

Exactly **113** columns, in `features.load.COLUMNS`:

```text
load_lag_72, load_lag_168, temperature, heating, cooling,
hour_sin, hour_cos, year_sin, year_cos, holiday,
dow_0 ... dow_6, quarter_0 ... quarter_95
```

Lags are UTC-clock hours and retain an assumed 24-hour observation latency after
interval end; any reference later than the 09:00 cutoff is masked. `temperature`
is the six-site weighted mean; `heating=max(15−temperature,0)`,
`cooling=max(temperature−22,0)`. Cycles use local clock / 365.25-day annual phase;
weekday and local quarter-hour are one-hot indicators. The nationwide German
holiday list is generated in `holidays`; regional and Luxembourg-only holidays
are omitted. DST repeated quarters share local indicators but retain distinct UTC
intervals. No installed-capacity normalisation, price, solar or wind input is used.

The 72-hour lag, rather than 48 hours, leaves room for the assumed 24-hour actuals
latency across the whole next-day horizon. The weekly lag captures working-week
recurrence. The latency mask is the implemented rule; historical retrievals do
not independently prove that every lag value was published within that allowance.

### 5.3 Architecture and choice

[QuantileLoad](../src/grid_signals/forecast/models/load.py) fits 19 direct
LightGBM quantile regressors, sorts their predictions and clips below at zero.
It has **no wind/solar CQR layer**. Fixed settings: 300 trees, 15 leaves,
learning rate 0.05, minimum child samples 80, L2 penalty 1.0, four threads,
`random_state=42`. Fixed protocol, no parameter search.

Load repeats daily/weekly and responds nonlinearly to temperature and working
days; the lags/calendar/degree terms encode those mechanisms while the GBM can
combine them. Six-site equal weights and 15/22°C thresholds are initial declared
assumptions, not proven optimal spatial weights or temperature breakpoints.

[load.backtest/publish](../src/grid_signals/forecast/pipelines/load.py) selects
lowest development CRPS then MAE and records `load_protocol.json` before final
evaluation. The selected model is `load_quantile_gbm`; its selection record checksum
must match the code version record before manual publication. Publication fits
on at most 730 days with `delivery_day < issue_day − 1 day` (24-hour availability
slack), requiring 180 distinct complete days. It still fits during the manual
forecast command, with no new schedule or saved-model lifecycle.

The historical comparison includes weekly 168-hour persistence with empirical
residual quantiles, median-imputed/scaled ridge (`alpha=10`) and median LightGBM
with last-30-day out-of-sample residual dressing. Those alternatives test value
beyond weekly recurrence and a simpler temperature response; they are not all
served daily. Full development/final results and the undercoverage distinction
are in section 7.

## 6. DE-LU prices

### 6.1 Source and fetching

The selected forward model is declared in
[price_forward.yaml](../src/grid_signals/forecast/configs/price_forward.yaml),
separately from the earlier price GBM experiment. Its only external input is
ENTSO-E **A44 DE-LU SDAC auction prices**, EUR/MWh, using `entsoe-py` 0.7.11's
classification sequence 1 (not EXAA). See [sources/prices.py](../src/grid_signals/forecast/sources/prices.py)
and the pinned client dependency in `uv.lock`. Earlier hourly prices can train
LEAR; quarter-hour targets are treated as native only from local **2025-10-01**.
A complete post-transition hourly aggregate requires four reported quarter-hours.

Manual `forecast --product de-price` calls `prices.refresh` for [D−8, D+1), but the
generic `entsoe.fetch_chunk` **returns the cache for an identical existing date
chunk**. A request is not proof that a fresh revision was downloaded. Parsed rows
carry `fetched_at`; overlapping files are resolved by latest retrieval. This path
has no SE3-style immutable raw-XML fetch receipts or automatic Prefect schedule.
Seed sufficient history through `fetch-price START END`.

### 6.2 Features

`Lear.fit` selects **103** inputs:

```text
profile_d{1,2,3,7}_h{00..23}       96 prior local-day hourly prices
dow_{0..6}                       7 delivery weekday indicators
```

Profiles are relative to delivery day D, so D−1 is the issue-day auction curve
already published on the preceding day. Quarter-hours are averaged to hourly
profiles; a repeated DST hour is averaged into its local-hour slot. Training days
missing one of 24 target hours are omitted by LEAR; missing input profile cells
are training-median imputed. The forward guard verifies every real hourly interval
in the four reference days, so a spring 23-hour day does not require a fabricated
02:00 observation. Price lags/quarter/month also constructed by `prices.features`
are **not selected by LEAR**. No load, renewable generation, weather or public
fundamental forecast enters this serving model.

### 6.3 Architecture and selection

[Lear](../src/grid_signals/forecast/models/price.py) is a **price-only LEAR
adaptation**, not an exact implementation of the full exogenous epftoolbox model.
It fits 24 separate hourly linear LASSO regressions using
`LassoLarsIC(criterion="aic", max_iter=500)`. Training-only median imputation,
median/MAD scaling (floor scale to one if < 1e-8), and `arcsinh` transformations
handle missing/extreme/negative prices. Predictions invert the target transform.
LASSO sparsity limits the contribution of correlated prior profiles; AIC selects
regularisation within each training fit.

`ResidualDistribution` first fits on days preceding the last 30 training days,
uses those 30 days' out-of-sample errors for 19 empirical residual offsets, then
refits the point model on all training days. Add offsets to hourly point prices
and repeat across quarter-hours. Prices are not clipped to zero. Uncertainty is
an empirical marginal residual distribution, not a direct conditional quantile GBM.

[price_forward.publish](../src/grid_signals/forecast/pipelines/price_forward.py)
uses up to the trailing 730 calendar days through the issue day inclusive, with
at least 180 distinct days and complete hourly training aggregates. Unlike
observed generation/load, the issue day's price curve is already knowable at
cutoff. It fits during each manual forecast call. There is no saved model or new
German production schedule.

The forward choice was made on 2026-10-15 **after both recorded price evaluations**:
LEAR had the lowest MAE/CRPS on both, while the custom-load GBM experiment did not
resolve a gain. Thus the final table is an honest historical comparison of fixed
methods, but it is not an untouched independent test of the later LEAR selection
decision. New forward evidence is required. Price-only inputs also avoid unverified
historical publication vintages for exogenous fundamentals. Weekly naive and
median/direct-quantile GBMs remain historical comparators, not the selected forward
model. Their full protocols/results are linked below.

## 7. Evaluation evidence and limits

The [evidence index](../research/README.md) summarises outcomes and links each
frozen protocol, development comparison and final result. [Metrics](metrics.md)
defines populations, units, bias signs and confidence intervals. Earlier hourly
boards describe different weather timing and must not be quoted as current skill.

The model choices above draw on the
[MEPS/IFS comparison](../research/reports/meps_archive.md),
[calibration comparison](../research/reports/calibration.md),
[quarter-hour comparison](../research/reports/products_15min.md) and the linked
load/price evaluations. The [custom-load price experiment](../research/reports/price_load.md)
did not establish a resolved gain and is not a serving input.

The renewable final protocol uses monthly refits with a seven-day embargo. The
new daily saved-model policy has **no separate completed accuracy backtest or new
live score series recorded here**. Do not present historical 2.46% wind nMAE as
its independently measured result. Migration and fitted-versus-reloaded checks
verify implementation; the [local verification record](archive/operations-record.md#local-verification--2026-11-01)
retains timings, resource measurements and restart/restore evidence.

## 8. Run and inspect the pipeline

- [Architecture and service boundaries](implementation-plan.md#how-the-deployed-system-should-run).
- [Exact schedules, data fetching and task bounds](operations.md#schedules-and-task-bounds).
- [Model, input, forecast and receipt files](operations.md#monitor-runs-and-inspect-files).
- [Bootstrap, deployment and scheduler cutover](operations.md#se3-producer-deployment--milestone-2b).
- [Publication identity, eligibility and failures](integration_contract.md).

## 9. Source documentation and evidence boundaries

Provider references checked 2026-11-02:

- [Open-Meteo Previous Runs](https://open-meteo.com/en/docs/previous-runs-api)
  defines fixed information-age offsets; [Single Runs](https://open-meteo.com/en/docs/single-runs-api)
  defines named initialisation runs. Repository archive-start constants are dated
  measurements; provider coverage and model implementations may change.
- [MET Norway THREDDS catalogue and service terms](https://thredds.met.no/thredds/catalog/meps25epsarchive/catalog.html)
  request serial access to the shared service and provide licensing/status links.
  Follow attribution requirements; public archive access is not an availability SLA.
- [ENTSO-E detailed data definitions](https://eepublicdownloads.entsoe.eu/clean-documents/Transparency/MoP_Ref2_DDD_v3r4.pdf)
  describe target definitions and forecast timing. API document/process codes are
  implemented in the pinned client and our source wrappers. Historical revisions
  and capacity publication vintages must not be assumed known at issue time.
- [Vindbrukskollen information](https://www.energimyndigheten.se/energisystem-och-analys/elproduktion/vindkraft/vindbrukskollen/)
  identifies the registry; our exact local file path, fields and download URL are
  in `sources/fleet.py`. Its service updates do not automatically update our seeded copy.
- [pvlib PVWatts DC](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.pvwatts_dc.html)
  documents the solar conversion used here. The project lockfile, not the current
  documentation site's default version, fixes our installed dependency version.
- [Open-Meteo service terms](https://open-meteo.com/en/terms) specify access/usage
  conditions and limits. The code's pacing/retry constants are implementation
  choices, not a substitute for current provider conditions or an uptime promise.

Reasons supported by project experiments are linked to those experiment reports.
Reasons supported only by domain knowledge or engineering constraints are labelled
as assumptions above. Missing ablations, issue-time vintages and daily-policy
accuracy evidence remain explicit gaps; this documentation does not manufacture
experiments or claim deployment that has not occurred.
