# ERA5 ceiling — how much of SE3 wind can the actual weather explain?

**Run:** 2026-09-21. Reproduce with
`PYTHONPATH=research/src uv run --group research python -m renewable_forecast.pipelines.pull_era5`
then `... -m renewable_forecast.pipelines.era5_ceiling`. Every number below is in
`era5_ceiling_tables.md`, which the pipeline writes. The holdout (March 2026 on) is not
touched: ERA5 is pulled only through 2026-02-28.

## The question

The day-ahead model misses by 136 MW per hour (point MAE, scored window). Is that the
weather forecast being wrong, or is something else limiting accuracy? ERA5 is the closest
archive to *what the weather actually was*. A model fitted to it is not a forecast; its
error is a ceiling on how much generation any weather-driven model can explain.

## What was built

The richest weather-to-power chain the project has, so that no simplification can be
blamed for a miss:

- **Every turbine on its own ERA5 cell.** 1,920 SE3 onshore turbines on 185 cells, not
  eight cluster centroids.
- **Wind carried to each turbine's own hub height**, using shear measured hourly between
  10 m and 100 m.
- **A power curve per turbine from its specific power** (W/m² of rotor), corrected for
  air density and smoothed for spread within a grid cell.
- **A live fleet:** each turbine counts only from its commissioning date.
- On top of that, LightGBM over physics, weather, per-cluster and calendar features.

## Findings

### 1. The pipeline is sound — nothing is broken in the chain

- **Physics with nothing fitted** correlates 0.98 with actual output, 2018–2026. With a
  single fitted gain it reaches R² 0.958.
- **Timestamps align in every era**, including after the December 2025 switch to 15-minute
  data. Correlation peaks with the weather shifted +0.25 to +0.5 h in all four eras,
  identically. The switch introduced no timing bug.
- **Icing is not a major error source**: hours with significant icing carry about 5% of
  the error.

### 2. On the backtest's own hours, perfect weather buys only 17%

The ERA5 model was trained on exactly the backtest's folds: same monthly origins, same
7-day embargo, same training window. It was then scored on the same 13,059 hours.

| model | MAE (MW) | RMSE (MW) | bias (MW) |
|---|---|---|---|
| SvK A69, latest revision (not a fair comparison) | 65 | 107 | 0 |
| **ERA5, actual weather** | **112** | **154** | **−1** |
| Day-ahead LightGBM (ships) | 136 | 185 | +12 |
| Physical power curve (NWP) | 158 | 213 | −17 |

The ERA5 error is **2.6–2.9% of installed capacity in every year from 2018 to 2026**, so
this ceiling is structural, not a quirk of the recent window.

The ceiling and forecast errors correlate only 0.32 hourly (0.42 daily), so most of the
ceiling error is not the forecast's error. Two things contribute: what ERA5 itself
cannot resolve (31 km grid, known low-level wind errors), and what no weather data
contains at all (availability, curtailment, grid constraints).

**Implication:** better weather data can close at most about 24 MW of the 136 MW,
unless it resolves more than ERA5 does. MEPS at 2.5 km could. SvK's 65 MW shows the target itself is
not that noisy, but its latest revision almost certainly uses information unavailable at
day-ahead time.

### 3. What was missed: capacity added since 2018 delivers ~70% of expected output

Actual output divided by physically expected output, *with the weather held fixed*:

| | 2018 | 2020 | 2022 | 2024 | 2025 | 2026 Q1 |
|---|---|---|---|---|---|---|
| actual / physics | 0.99 | 0.95 | 0.93 | 0.85 | 0.86 | 0.81 |

This is the ceiling-drift problem in `README.md` §3, now confirmed with the weather
removed as an explanation. Splitting expected output into the fleet that existed at
the start of 2018 (gain 1.02 in 2018) and everything added since shows the pattern:
**the added capacity produces 0.65–0.80 of its physical expectation every quarter since
2019.** The overall ratio falls because that capacity grew from 0% to 55% of the fleet.

Candidate causes, not yet separated:

- **Wake losses in large modern parks.** The old fleet is small, scattered machines with
  few wakes; new capacity comes in big arrays. Typical wake losses of 10–15% explain part
  of the gap, not all of it.
- **The registry versus reality.** Commissioning dates earlier than first production,
  turbines listed as built that are not yet exporting, or parks whose output is missing
  from ENTSO-E's SE3 series.
- **Grid or market curtailment**, which grows with the fleet (see §4).

**Consequence:** a model trained on 2018–2023 and scored on the backtest window over-predicts
by **+65 MW** (MAE 127 vs 112). Long ERA5 history can only be used for training once
this drift is modelled. The capacity-factor target is distorted by the same mechanism.

### 4. Negative-price hours are curtailed

On the 551 scored hours with negative day-ahead prices, the ERA5 model over-predicts by
**+184 MW** on average, and the day-ahead model's MAE is 224 MW. No weather data contains
this. The day-ahead price is not known at issue time, but negative prices are
forecastable: a price-risk feature, or a curtailment term in the post-processing, is the
lever here, not better weather.

### 5. The remaining error is diffuse

The worst 10% of days carry 23% of the ceiling's error; the worst 1% carry 3%. Error
grows with output: 49 MW when expected output is under 10% of capacity, about 155 MW above
40%. There is a mild seasonal bias, +30 to +60 MW in winter and spring and about −60 MW
in autumn, which is consistent with seasonal availability or icing that ERA5's surface
fields do not capture.

## What to do with this

1. **Model the added-capacity shortfall** instead of letting the tree absorb it as a
   level shift. The cheapest version is a fitted gain per commissioning cohort or per
   park size. It also fixes the capacity-factor denominator.
2. **Add a negative-price or curtailment term.** It is worth ~180 MW on ~4% of hours.
3. **Expect MEPS to help, but not dramatically.** The gap between perfect 31 km
   weather and the current forecast is ~24 MW.
