# Improvement roadmap — SE3 day-ahead wind

Refined 2026-09-21 from `docs/literature.md` and fresh diagnostics on the backtest.
It replaces the short list at the end of the README. Numbers marked *start* are
starting points to change freely. The fixed constraints are the frozen protocol
(`reports/protocol.md`), the sealed holdout, and the information-age test.

## Where each change plugs in

```
 NWP sources                         features            model                calibration            output
 ───────────                         ────────            ─────                ───────────            ──────
 Open-Meteo Previous Runs ─┐
   (whole-day vintage, P2) │
 MEPS det_hl 00z ──────────┼──► point features ──► design ──► LightGBM ──► conformal layer ──► 19 quantiles
   (run-addressed) [B1] ✓  │     + physics          matrix     quantiles    (SpreadCQR, A2 ✓)  ──► scenarios
 IFS HRES single runs ─────┘     power curve          ▲          ▲
   (run-addressed) [B2] ✓                             │          │                ▲
                                                      │          │                │
 ENTSO-E actuals ──► target  cf = MW / capacity ──────┘          │         NWP spread column
 Turbine registry ─► capacity (installed → effective) [C1]       │         (model disagreement)
                                                                 │
  issue-day prices [D2], recent residual [D1] ───────────────────┘
 evaluation: coverage by *forecast* bin, spread–skill, PIT, day-block tests [A1]
```

## What the diagnostics add to the literature

Four checks run on the persisted backtest (`data/predictions/`, 13,082 hours) changed
how the problems rank.

1. **Part of the "high-wind" shortfall comes from how the chart bins hours** (Lerch et al.
   2017). Binned by *actual* output, 80% coverage in the 0.6–0.8 bin is 0.696. Binned by
   the *forecast* median it is 0.719. The real shortfall is broad: 0.76 → 0.73 → 0.69 →
   0.72 across forecast bins.
2. **The shortfall is in both tails, and it shifts with season.** Truth falls below p10
   12.7% of the time and above p90 13.7%, so the bands are too narrow on both sides. By
   season it tilts: DJF falls *below* p10 17% of the time (winter over-prediction), and
   SON falls *above* p90 20% of the time (autumn under-prediction).
3. **NWP disagreement predicts error, and the model under-uses it.** Take hours whose raw
   p10–p90 width is the same, and sort them by the spread of the three models' power
   curves. Mean absolute error rises with spread in four of five width quintiles (about
   2× in the narrower ones), and 80% coverage falls from 0.81 to 0.67. This is the spread–skill test
   Thorarinsdottir & Gneiting (2010) describe, and it passes. Browell et al. (2020) and
   Dantas & Browell (2025) found ensemble spread of little use *on average*. Here the
   signal is not in the average: it sits in the conditional width, and the calibration
   layer ignores it.
4. **Daily bias persists.** The lag-1 autocorrelation of the daily mean error is 0.32, and
   0.15 at lag 2. Only part of that is usable: at issue time just the first hours of the
   current day are observed. The anomaly of the recent physics residual correlates
   0.13–0.17 with the next delivery day's mean error (see D1).

## Tracks, in order

### A — Calibration (P1). Cheapest, and directly measured

- [x] **A1. Fix the evaluation first.** Bin conditional coverage by forecast, not by
  outcome. Add a spread-conditioned coverage breakdown. *Why first:* a result judged on
  outcome bins can reward hedging (Lerch 2017).
- [x] **A2. Spread-aware conformal layer (`SpreadCQR`).** Strata are predicted level ×
  NWP-spread tercile. **Done, ships** (`reports/calibration.md`): CRPS unchanged within
  noise, 80% coverage 0.737 → 0.774 and flat across spread quartiles. Additive scores
  beat width-normalised ones. The remaining gap is autumn (0.73), which is drift, so
  it moves to A3/A5.
  Evidence: diagnostic 3; Moradi 2025 (context-weighted conformal); Romano 2019
  (normalised CQR); Gibbs 2024 (group-conditional coverage). The old strata (lead × level)
  left ~11 calibration rows per cell in early folds, so most fell back to the global
  correction. A/B in `pipelines/compare_calibration.py`.
- [x] **A3 result: cross-fitted calibration ships.** CRPS −3.7% (significant), nMAE
  −3%, 80% coverage 0.765 → 0.784, SON 0.73 → 0.78 (`reports/calibration.md`). Season
  strata on top hurt. Original note:
- **A3. Use the calibration quarter for fitting as well.** The shipping booster never
  sees the most recent 25% of its window, because those days are reserved for
  calibration. Options: refit on the full window after calibrating (tested as an arm
  in A2), or cross-fit so every training day gets an out-of-sample prediction. Cross-
  fitting also gives a calibration set four times larger.
- [ ] **A4. Tail-specific regularisation** (Landry 2016). The outer quantiles get more
  conservative settings. Cheap. Try it only if A2 leaves the tails short.
- [ ] **A5. Second-stage recalibration as an alternative to conformal**: quantile
  regression on the first-stage quantiles (Lindberg 2023/2024), or a beta-transformed
  pool (Gneiting & Ranjan 2013). Both need a separate calibration block. Try this only if
  A2's seasonal tilt persists, since both can absorb a level shift that conformal widths
  cannot.
- Not planned: an ECMWF ENS feature from dynamical.org. The 00z run arrived after the
  summer cutoff until 2025-10-02 (literature §4), and the literature expects little
  gain at 14–38 h. Revisit only as a worst-day analysis, or once A2 has used up the
  cheaper spread signal.

### B — Run-addressed NWP (P2). The largest measured structural error

- [x] **B1. MEPS A/B** (`pipelines/compare_meps.py`, `reports/meps_archive.md`).
  Adding MEPS to the Open-Meteo block: **nMAE −9%, CRPS −8%**. MEPS alone removes the
  lead-34 step but is a weaker signal (one 2.5 km cell per cluster), so the combined
  model keeps leaning on the stale block and the step survives. Fixed on the way: the
  A/B sealed its holdout relative to the MEPS frame and discarded Sept 2025 – Mar 2026.
- [ ] **B1b. MEPS neighbourhood.** Average a box of cells around each cluster instead
  of one cell, and keep the box's spread as a pseudo-ensemble (Molinder 2018). Needs
  a re-pull (~2 h): the puller already fetches the box but stores only the centre cell.
- [x] **B2. ECMWF IFS HRES from the Open-Meteo Single Runs API.** Pulled: 713 runs,
  2024-03-14 → 2026-02-28, four runs missing in August 2025. The run-addressed IFS power
  curve correlates 0.967 with output, the best single input so far (Open-Meteo
  three-model mean 0.965, its day-vintaged 0.25° sibling 0.956). A/B:
  `compare_meps --ifs`. Verified 2026-09-21:
  `models=ecmwf_ifs&run=2024-09-01T00:00` returns 48 hourly steps with 100 m wind. GFS and
  ICON-EU runs from 2024 are *not* available there. This gives a run-addressed global
  model to pair with MEPS, at ~745 requests for eight points (one multi-location request
  per run). Pinned model: `ecmwf_ifs` (9 km HRES), not the `ecmwf_ifs025` used today.
- [x] **B2 result:** `all` (Open-Meteo + MEPS + IFS runs) **−12% nMAE, −11% CRPS**
  against the shipping feature set. Run-addressed sources alone: −6% nMAE, lead-34 step
  +45% → +14% (`reports/meps_archive.md`).
- [ ] **B4. Live path.** `assemble.build_operational` and `pipelines/predict.py` must
  fetch the day's MEPS 00z and IFS 00z runs, or the live forecast will not be the one
  that was backtested. MEPS latest runs are on thredds' operational catalogue, not the
  archive; the IFS run comes from the same Single Runs endpoint.
- [x] **B3. Decide what happens to the whole-day block.** Keep it: it still adds
  3–5% CRPS on top of the run-addressed sources. Original note: Once B1/B2 land, GFS and
  ICON-EU remain only on whole-day offsets, and ICON-EU cannot be run-addressed for the
  backtest window at all (literature §4). Options: keep them as spread-only inputs, or
  drop them. Their disagreement is the spread signal A2 uses, so replace the spread
  column before dropping them.

- [x] **B5. Time-lagged IFS (previous day's 18z run) — tried as a feature, not adopted.**
  Pulled 18z runs (archive starts 2024-08-06, so it covers 12 folds). Pooled CRPS is
  unchanged (0.0205 → 0.0205). But the 00z − 18z jump is a strong *uncertainty* signal:
  the 259 hours where the power curve moved by more than 0.1 CF between runs have 1.6× the
  normal error, and 80% coverage of 0.67. As a feature it lifts their coverage to 0.73.
  Candidate follow-up: use `power_curve__ifsrun_jump_abs` as a second stratifier in
  `SpreadCQR` rather than as a tree input (`compare_blocks --lagged-ifs`).
- [ ] **B6. Self-archive MEPS neighbourhood from now on.** `pull_meps --radius 4` works
  on live runs, but the thredds archive now lists only 2026-09, so it cannot be
  backtested. Run it daily alongside `predict` until enough history exists.

### C — Capacity denominator (P3)

- [ ] **C1. Effective capacity for the training target.** The ERA5 cohort study finds
  capacity added since 2018 delivers ~70% of physics-expected output. Train on
  `MW / effective capacity`, where effective = pre-2018 cohort + *k* × later additions
  (*k* from 2019–2023 cohort data, *start* 0.7; the backtest window alone cannot identify it), and multiply back before
  scoring. Scoring stays against installed capacity, as frozen. Precedents: Bellinguer
  2020 (mean of registered capacity and running maximum) and Browell 2020 (manual
  correction: −5% capacity, −10% pinball in SE1).
  **Expected effect inside the backtest window is small.** The added-capacity share
  only moves from 0.48 to 0.55 between 2024-Q1 and 2026-Q1 (`era5_ceiling_tables.md`),
  so at *k* = 0.7 the effective denominator drifts ~2.5%, about 35 MW at typical output.
  C1 matters mainly as the precondition for training on 2018–2023 history (ERA5-driven
  or reanalysis-trained, as in Wanek 2026), where the share moved from 0 to 0.47.
  Fit *k* on 2019–2023 only, so no backtest-window information enters.
- [ ] C2. Before any further attribution work: flag hours that look like downtime or
  curtailment (zero or flat output against high forecast wind; Lindberg 2023, Olauson
  2018, IEA 13.2.1). Drop them from training only, and report how many there are.

### D — Use information the model already has at issue time

- [x] **D1. Recent-residual feature — tried, not adopted.** Built
  (`assemble.residual_features`) and A/B'd on the `all` matrix
  (`pipelines/compare_blocks.py`, 18 folds): CRPS 0.0204 → 0.0204, nMAE 0.0271 →
  0.0269. The booster evidently gets the same information from the lagged-actual and
  level features. Original note: At 09:00 UTC, actuals are known up to about 08:00
  on the issue day. The error of the physical power curve over the last *n* observed
  hours (*start* 24) is a legitimate feature, provided its information age is registered
  with the leakage guard. It targets diagnostic 4 and the "confidently wrong for 24
  hours" failure of 2026-02-13. Lorenz 2011 (sliding-window bias correction) and Pinson
  & Kariniotakis 2010 (time-adaptive) are precedents. Risk: redispatch shutdowns corrupt
  generation-derived features (Meisenbacher 2025), so clip the feature and compare it
  with and without C2's flags.
- [x] **D2. Curtailment risk from prices — tried, not adopted.** Built
  (`assemble.price_features`). Pooled CRPS 0.0204 → 0.0203 (n.s.). On the 541
  negative-price hours it does not move CRPS (0.0292 → 0.0293), and the bias there stays
  at about −30 MW. Issue-day prices are too indirect a proxy for delivery-day
  curtailment. Retry only with an explicit curtailment label (C2). Original note: In the old backtest, hours whose same hour on the issue
  day was negative-priced had a bias of −42 MW, against −11 MW elsewhere (552 hours). On the 551 backtest hours with negative
  day-ahead prices, the ERA5 model over-predicts by +184 MW and the day-ahead model's MAE
  is 224 MW (`reports/era5_ceiling.md` §4). The delivery day's prices are not known at
  09:00, but the issue day's are: they were published at about 13:00 CET the day before.
  Candidate features: whether the same hour on the issue day was negative, and the number
  of negative hours that day. Evaluate on those hours specifically, and let the
  calibration layer see the feature too, since curtailment is a one-sided risk.
- [ ] D3. Neighbour-zone median layer (Landry 2016, Browell 2020): SE2/SE4 first-stage
  medians as inputs. Lower priority; it needs the SE2/SE4 targets built.

### F — Seasonal bias (open)

- [x] Tested whether the day-of-year features memorise one year's seasonal anomaly:
  dropping `doy_sin`/`doy_cos` changes nothing (SON bias +0.0119 → +0.0116, CRPS
  identical). The ERA5 study sees the same pattern with *actual* weather (winter/spring
  over-prediction, autumn under-prediction), so it lives in the data — availability,
  icing, maintenance seasons — not in the model. Needs an outage/availability source
  (C2), not another feature transform.

### E — Later, unchanged from the README

- P4 15-minute output: design from IEA 13.2.2 (averages versus instantaneous values);
  little literature exists.
- German solar: register-based physical model with one derating factor (Saint-Drenan
  2017). The TSO "actual" is itself an estimate, so fix the denominator, the hours that
  count, and the benchmark before modelling (van der Meer 2018).

## Stopping rules

- Each item is judged by a same-rows A/B on the development folds, with CRPS as the
  headline metric and coverage reported alongside it. Differences under ~3% relative
  are not significant at this sample size (protocol).
- The holdout opens once, after tracks A–D are settled.
- No hyperparameter search. A2's bin counts and D1's window length are chosen by
  argument, not by sweeping the folds.
