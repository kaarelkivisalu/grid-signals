# Historical research backlog

**Archived priorities.** The [project roadmap](../../ROADMAP.md) owns the agreed
Nordic/Baltic direction and delivery order. The options below preserve earlier
experiment ideas and measured resource estimates; they are not parallel workstreams
or current completion checklists. Some tasks, including local scheduling and final
holdout evaluation, have since been implemented. See the
[research README](../README.md) for results and
[target architecture](../../docs/implementation-plan.md) for the current boundary
and the planned retirement of components that no longer serve the forecast product.

Any experiment selected later needs a protocol appropriate to the then-available
data. The completed holdouts must not be reopened for model selection.

## Original planning context

Remaining work after the 2026-10-15 quarter-hour and solar implementation. Where the project stands today is in the
README. The evidence behind finished work is in `reports/` (see the index at the end).
Numbers marked *start* are starting points, not commitments. Four things are fixed:
the frozen protocol (`reports/protocol.md`), the sealed holdout
(2026-03-20 → 2026-09-19), the information-age test, and same-rows A/B comparisons for
every change.

## Where the planned work plugs in

```
 NWP sources                              features / model                     output
 ───────────                              ────────────────                     ──────
 Open-Meteo Previous Runs (whole-day) ─┐
 MEPS det_hl 00z (run-addressed)     ──┼─► point features ─► LightGBM quantiles ─► SpreadCQR ─► 19 quantiles
 IFS HRES 00z (+18z) (run-addressed) ──┘   (8 clusters)      (cross-fitted)       (level x    hourly fit, SE3 wind
                                                 │                                 spread)       │
   [2] gridded NWP + turbine map ──► [2] spatial model (CNN) ─────────────────────┘             │
                                                                                                ▼
 ENTSO-E actuals ─► target (MW / capacity) ◄── [5] availability / effective capacity     [1] 15-minute output
 Turbine / PV registries ─► capacity                                                     [3] DE-LU solar
                                                                                         [4] second wind zone
                                                                                         [6] more bidding areas
```

## 0. Housekeeping (small, do first)

- [ ] **Keep weather inputs current.** MEPS access recovered; the October refresh and
  its explicit upstream gaps are recorded in `reports/products_15min.md`. Repeat with
  `pipelines.refresh_archives`, which backs up parsed weather and emits a coverage
  manifest. New input dates can feed production fitting without moving or scoring the
  frozen holdout.
  - Re-pull the development window with `pull_meps --radius 4` (~2 h). The single-cell
    MEPS signal is noisy (corr 0.936, against 0.959 for 0.25° IFS). The 9 × 9 mean and
    its spread are coded but not yet backtested.
- [ ] **Schedule the daily run.** `predict` at 09:00 UTC, after IFS 00z availability. It
  already self-archives the day's MEPS and IFS runs. Add the MEPS neighbourhood pull to
  the same job.
- [ ] **Capture the TSO forecast (A69) at issue time**, one request per day. The archive
  serves only the latest revision, so this is the only way to get an honest day-ahead
  benchmark (protocol, "A69 is not a day-ahead benchmark").
- [ ] **Schedule weather backups.** `refresh_archives` takes a local snapshot before a
  refresh; copy those snapshots off-machine and set retention. The parsed store is
  gitignored and upstream archives can go offline.

Feature aggregation is now vectorised for the quarter-hour path. Re-measure the
resource table in §6 before using its September timings for scaling decisions.

## 1. 15-minute output — raised priority

Stage 1 is implemented and evaluated. The operational default repeats hourly
forecasts on the quarter-hour grid: interpolated weather showed no significant CRPS gain,
although it improves median ramp MAE. The interpolation candidate remains available
with `predict --wind-method interpolate`. The protocol
amendment fixes three development months (December 2025–February 2026), compares the
same rows against repeated hourly predictions, and preserves the original hourly
board and sealed holdout. Results, ramp diagnostics and commands are in
`reports/products_15min.md`. Solar trains and forecasts natively at 15 minutes.

- [ ] **Stage 2 — native 15-minute training** once enough 15-minute history exists
  (roughly a year, around 2026-12). Pre-December data enters as hourly averages with a
  resolution flag, or is dropped.
- [ ] **Joint ramp uncertainty.** Median ramp magnitude and timing are scored by the new
  product backtest. `models/scenarios.py`
  (Schaake shuffle, Gaussian copula) already produces temporally coherent paths;
  scoring them needs the energy or variogram score over the delivery-day vector.
- Watch: MEPS and IFS are hourly, so sub-hourly skill must come from interpolation and
  from the statistics. Open-Meteo `minutely_15` exists for some models, but not for a
  backfilled, run-addressed archive.

## 2. Spatial model: gridded NWP and a turbine map (literature §5, Jonkers 2024)

Jonkers et al. (2024) stack a **turbine map** (capacity rasterised onto the NWP grid) as
an extra channel next to gridded NWP. They train one DenseNet across all four EEM20
Swedish zones and beat every competition entry. The same map is also their answer to
fleet change: the model sees where capacity is, not a fixed zone. WindDragon (Keisler
2025) confirms that full NWP maps beat a collapsed mean for French regions. Uselis
(2020) warns that the advantage of spatial encoding fades with lead time. Both were
tested at short horizons, not at 22–46 h.

- [ ] **Stage 0, no deep learning.** Store the MEPS bounding box per run instead of eight
  points. Compute a *capacity-weighted mean of per-cell power*: every turbine on its own
  2.5 km cell, which is the ERA5 study's turbine-level fleet model applied to forecast
  weather. Feed it to the existing booster. This captures much of the turbine-map idea
  cheaply and is the baseline a CNN must beat.
- [ ] **Stage 1, CNN.** Input channels: MEPS fields cropped to the zone plus a buffer, IFS
  upsampled, and the turbine map (capacity per cell as of the issue date). Target:
  zonal CF. Keep the existing `SpreadCQR` + cross-fit calibration on top, since Jonkers
  also find uncalibrated deep models overconfident. Their logit-transformed conformity
  score is worth testing on the current model first (§5).
- [ ] **Stage 2, one model for several zones.** The turbine map is what makes this
  possible. It links directly to §4 and §6.
- Resources: see §6. Rough per-zone storage is ~11 GB of float16 MEPS crops for two
  years. Training wants one GPU (≥12 GB); CPU-only is possible but slow for
  rolling-origin backtests.

## 3. Solar, DE-LU — improve the initial forecast

The first quarter-hour model is implemented and operational forecasts are archived.
It uses pinned ECMWF Previous Runs irradiance, clear-sky-index interpolation, a
PVWatts physical chain, daylight-only quantile fitting and explicit zero-at-night
bounds. Daylight-only development evaluation compares it with PV physics, smart
persistence and clear-sky climatology. See `reports/products_15min.md`; the sealed
holdout remains untouched.

- [ ] **Dated MaStR fleet and denominator.** Replace the declared equal-area six-site
  lattice and annual A68 snapshots with installed capacity, locations, commissioning
  dates and panel orientation mix from the registry. Annual capacity is currently
  carried forward from a preceding snapshot; future anchors are never used. Historical
  A68 publication vintages are not available.
- [ ] **Run-addressed solar weather.** Add IFS HRES radiation, stored under its own task
  namespace. The initial solar model uses a whole-day-vintaged ECMWF archive, so its
  interpolation endpoints are included in the information-age check. ICON can be
  forward-archived; no consistent run-addressed 2024–25 archive is established here.
- [ ] **Solar-specific calibration.** Initial nominal coverage is measured in the new
  product report; do not assume wind's calibration transfers. Test reliability by
  output, cloudiness and season on development rows only.
- [ ] **Better physical assumptions.** Registry orientation mix, thermal model,
  clear-sky-index interpolation around sunrise, one derating factor per control area
  and improved snow handling. A basic snow flag is implemented.

German TSO actuals are upscaled estimates, so an observation error floor remains.
The operational dry-run and final holdout evaluation are still required before
integration.

## 4. A second wind zone — does SE3 generalise?

Every finding so far comes from one zone. Before §6, check that the pipeline and the
conclusions transfer.

- [ ] **In-country control: SE4 or SE2.** Same registry, same MEPS domain, same data
  quirks. Does the run-addressed gain, spread calibration and cross-fit reproduce?
- [ ] **Out-of-country: Finland (FI)** recommended.
  - One zone, a large and fast-growing fleet, inside the MEPS domain, icing.
  - Fingrid open data has two things this project lacks for SE3. Dataset 246 is a
    next-day wind forecast updated **once a day at 12:00 Finnish time**: a fixed daily
    vintage made at roughly our issue time, so an honest TSO day-ahead benchmark.
    Dataset 268 is the total capacity Fingrid's own forecast uses, a ready-made
    denominator to check a registry against. Checked 2026-09-22 on the dataset pages;
    whether the archive keeps every past daily issue, rather than the latest per hour,
    still needs verifying.
  - Needs a turbine list with coordinates and commissioning dates for the clusters.
- [ ] **What to compare against SE3:**
  - the capacity-ceiling drift (is SE3's 0.91 → 0.79 Swedish-specific?);
  - the lead-34 step size;
  - coverage by spread and by season;
  - the seasonal bias pattern;
  - skill against physics.
  Kean & O'Sullivan (2026) found Nordic zones among the hardest to beat the TSO in, so
  expect differences.
- Optional third: DK1. Offshore is reported as its own type, so it tests an onshore
  model in a mixed zone.

## 5. Model and data improvements still open

Ordered by expected value per effort.

- [ ] **18z run-to-run jump as a calibration stratifier.** Hours where the 00z and 18z IFS
  power curves differ by more than 0.1 CF carry 1.6× the normal error and have 0.67
  coverage. As a tree feature it did nothing pooled; as a `SpreadCQR` stratifier it
  targets exactly those hours. The 18z archive starts 2024-08-06, so it is testable on
  12 folds.
- [ ] **Logit-transformed conformity scores** (Jonkers 2024): map CF through logit before
  scoring. It gave narrower intervals at equal coverage on EEM20. Cheap.
- [ ] **Availability and curtailment flags (was C2).** Flag hours with zero or flat output
  under high forecast wind (Lindberg 2023; Olauson 2018; IEA 13.2.1). Drop them from
  training only, and report how many. The seasonal bias (winter over-prediction, autumn
  under-prediction, ~±40 MW) also appears in the ERA5 study with *actual* weather, so it
  lives in availability, icing or maintenance patterns, not in the model. It needs a
  data source, not another feature transform. Candidates: ENTSO-E unavailability
  (A80/A77 outages; `grid-signals` already ingests outages), or a residual-based
  downtime detector.
- [ ] **Effective capacity (was C1).** Added capacity delivers ~70% of physics-expected
  output (`reports/era5_ceiling.md`). Inside the backtest window this is only a ~2.5%
  denominator drift. It matters as the precondition for training on 2018–2023
  (reanalysis-trained, as in Wanek 2026). Fit *k* on 2019–2023 only.
- [ ] **Tail regularisation** (Landry 2016): more conservative settings for the outer
  quantiles. Cheap. Only if tails stay short after the stratifier and logit items above.
- [ ] **Second-stage recalibration** (Lindberg 2023/24; Gneiting & Ranjan 2013 BLP). Only if
  a location shift remains that conformal widths cannot absorb.
- [ ] **Neighbour-zone medians** (Landry 2016; Browell 2020). Needs §4's zones built first.
- Not planned: an ECMWF ENS feature. The dynamical.org 00z run arrived after the summer
  cutoff until 2025-10-02, and the literature expects little day-ahead gain.

## 6. Expanding to other bidding areas

This section estimates what it would take to run the SE3 wind pipeline for many
zone-fuel pairs. The figures below are **measured** on this machine (12 cores, 15 GB
RAM) for SE3 wind, two years of hourly data (2026-09-22); anything else is marked as an
estimate.

### Resources per zone-fuel pair

| item | SE3 wind, measured | scaling notes |
|---|---|---|
| NWP storage (parsed + raw) | ~90 MB (Open-Meteo 24, IFS 00z + 18z 37, MEPS 18) | linear in points × years; 8 cluster points per zone |
| ENTSO-E storage | ~10 MB per SE zone; 45 MB for DE-LU | DE-LU carries every production type at 15 min |
| design matrix + backtest forecasts | 23 MB + 26 MB | ×4 at 15-minute resolution |
| ERA5 turbine-level study (optional) | 0.5 GB | only for reanalysis work |
| gridded NWP for §2 (estimate) | ~11 GB for two years of MEPS crops (160 × 160 cells, 8 fields, 38 leads, float16) | IFS 0.25° over a zone is <0.5 GB |
| one production fit (cross-fitted, 19 quantiles, 16.8k rows) | 166 s wall, 16 CPU-min, 0.6 GB peak RAM | ~linear in rows; ×4 rows at 15 min |
| one 24-hour prediction | 15 ms | negligible |
| feature assembly per build | ~2–3 min (MEPS block dominates) | vectorise first (§0) |
| full backtest leaderboard (7 forecasters, 17 folds) | 37 min wall, 3.6 CPU-h | the quantile model alone is ~30 min |
| typical A/B (2–3 arms) | 20–80 min wall | cross-fit arms cost 5× |
| GPU | none needed for the current stack | §2 CNN: one ≥12 GB GPU; tens of GPU-hours per full rolling backtest (estimate) |

What follows, for N zone-fuel pairs:

- **Daily inference is cheap. Daily *refitting* is the constraint.** Refitting at issue
  time costs ~5–6 min per pair, so 40 pairs would take ~4 h serially on this machine,
  which does not fit a 09:00 UTC window. Fit overnight (after the previous day's actuals)
  or weekly, and at issue time only fetch the runs, build features and predict (<1 min
  per pair).
- **Backtests scale linearly:** ~0.5–1 CPU-h per pair per model variant. A 40-pair
  leaderboard is roughly 1–2 days on this machine, or a few hours on a 64-core box.
  Nothing here needs a GPU unless §2 is adopted.
- **Storage stays small** (<0.2 GB per pair) without gridded NWP. With gridded MEPS for a
  CNN it is ~10 GB per zone, or less if neighbouring zones share one crop.

### Download budgets and rate limits

- **MEPS (thredds):** ~9 s per run for a bounding box, serial by the service's terms.
  Server cost is per request, not per byte (one full slice is decompressed either
  way), so **one Nordic-wide box per run can serve every MEPS zone at once**. A two-year
  backfill is ~2 h regardless of zone count; transfer grows with the box.
- **IFS single runs (Open-Meteo):** one multi-location request per run per zone. The
  first backfill hit HTTP 429 at ~13 runs/min, and 3 s pacing works. Weight grows with
  locations × variables, so many zones on the free tier take days of paced pulling. A
  commercial API key is the scaling path.
- **Open-Meteo Previous Runs:** heaviest per request (120-day chunks × 9 variables ×
  2 offsets). Same free-tier constraint.
- **ENTSO-E:** 400 requests/min; 30-day chunks work (`grid-signals` CLAUDE.md).

### Per-area issues to expect

| area | NWP coverage | capacity / registry | known issues |
|---|---|---|---|
| SE1, SE2, SE4 | MEPS ✓, IFS ✓ | Vindbrukskollen (as SE3) | SE1: production above registered capacity (Olauson 2015), icing, complex terrain. SE4: small fleet, so noisier CF. 15-min from 2025-12 |
| FI | MEPS ✓, IFS ✓ | needs a Finnish turbine list with coordinates; Fingrid dataset 268 gives forecast capacity | fast growth; icing; Fingrid dataset 246 (daily 12:00 EET forecast) is a candidate honest TSO benchmark |
| NO1–NO5 | MEPS ✓, IFS ✓ | NVE plant list | small fleets in several zones; complex terrain; Norway was hardest in Kean & O'Sullivan 2026 |
| DK1, DK2 | MEPS ✓ (domain edge; check per point), IFS ✓ | Energistyrelsen register | onshore and offshore reported separately; offshore is a few large concentrated parks |
| EE, LV, LT | MEPS ✓, IFS ✓ | national lists (Elering etc.), quality unknown | fleets of a few hundred MW to ~2 GW, so high normalised noise; LT growing fast. `grid-signals` already tracks EE |
| DE-LU | **no MEPS**; IFS ✓; ICON not run-addressable retroactively | MaStR (good, dated) | redispatch curtailment (5.7 TWh in 2024, Wanek 2026); TSO actuals partly estimated; huge fleet, so many more points; best first solar zone (§3) |
| PL | no MEPS; IFS ✓ | public register with coordinates not confirmed | already ingested by `grid-signals`; data completeness to check |

Common to all areas:
- ENTSO-E A69 is served as the latest revision everywhere, so honest TSO benchmarks need
  issue-time capture.
- 15-minute switch dates differ by zone.
- ENTSO-E installed capacity (A68) is annual, so a dated registry is needed for the
  denominator.
- Each new zone needs the data audit (`pipelines/data_audit.py`) and its GO/NO-GO
  before any modelling.

### Recommended sequence

§4 first (SE4 + FI), to learn what transfers. Then generalise the zone-specific parts
(registry loader, cluster building, MEPS box) behind one interface. Then add zones in
batches that share a MEPS box. The turbine-map CNN (§2) is the natural single model
across zones, if it beats per-zone boosters.

## 7. Evaluation and release

- [ ] **Open the holdout once**, after §0 and whichever of §1/§5 land before it, on
  both the hourly and the 15-minute score. Report it next to the development board,
  never in place of it.
- [ ] **Live trial (phase 7b):** 30+ scheduled issue days scored against actuals and
  against the captured A69 (§0).
- [ ] Significance on every headline claim with the day-block bootstrap; ~3% relative
  is the resolution limit at this sample size.
- [ ] Scenario scoring (energy / variogram score) before any product uses the paths.

## Tried and not adopted — don't redo without a new reason

| idea | result | where |
|---|---|---|
| Recent physics-residual features | CRPS unchanged | `compare_blocks` (D1) |
| Issue-day negative-price features | unchanged, including on negative-price hours | `compare_blocks` (D2) |
| 18z lagged IFS as tree features | pooled CRPS unchanged | `compare_blocks --lagged-ifs`; reused in §5 as a stratifier |
| Dropping day-of-year terms | no change; seasonal bias persists | `compare_blocks --drop` |
| Width-normalised conformal scores | slightly worse CRPS than additive | `reports/calibration.md` |
| Refitting on the calibration days without cross-fit | intervals too sharp | `reports/calibration.md` |
| Season as a calibration stratum | worse coverage | `reports/calibration.md` |
| MEPS 30-member ensemble | ends 2024-12-10, covers 18% of the window | `reports/meps_archive.md` |

## Index of results

`reports/modelling.md` (leaderboards v1, v2) · `reports/calibration.md` (track A) ·
`reports/meps_archive.md` (run-addressed NWP) · `reports/openmeteo_vintage.md` (the
lead-34 step) · `reports/era5_ceiling.md` (weather ceiling, capacity cohorts) ·
`docs/literature.md` (sources) · `docs/metrics.md` · `docs/dataflow.md`
