# Literature review — day-ahead wind and solar forecasting

Compiled 2026-09-21 for `research/README.md`. Scope: what the published record, vendor
documentation and grey literature say about the problems the README lists.

This is a supporting research library, not an active work plan. Priority labels
and README problem tags below reflect the original September study. Current
work follows [ROADMAP.md](../ROADMAP.md); model choices are explained in the
[model reference](../docs/dataflow.md). External-service details are dated notes.

**How to read this file**

- Downloaded PDFs are in `research/data/papers/` (gitignored); entries with a PDF name it under the reference line.
- Every DOI was resolved against Crossref (journal articles) or DataCite (arXiv) on the day
  of writing; the title and year returned matched. Where no DOI exists (NeurIPS, JMLR, data
  documentation) the URL is given instead.
- Each entry states what was actually read: **full text** (or substantial parts),
  **abstract**, **docs page**, or **metadata only**. "PDF added, not read further" means the file is on disk but I only checked the parts named. For *metadata only* entries the summary
  comes from general knowledge of the paper plus the verified title; treat it as a pointer to
  chase, not as a checked claim.
- A plain bullet is something the source says. A bullet starting with **→** is my inference
  for this project, not the source's claim.
- Problem tags follow the README: **P1** over-confident ranges · **P2** stale weather vintage
  in the back half of the day · **P3** capacity denominator drift · **P4** 15-minute market ·
  **SOL** German solar · **EVAL** how we score.

---

## 0. Highest-value leads

| lead | bears on | where | caveat |
|---|---|---|---|
| Run-addressed archives now identified for ECMWF (Open-Meteo Single Runs, from 2024-03-14; dynamical.org ENS, from 2024-04-01) and **GFS** (dynamical.org, from 2021-05-01, 100 m wind, every 6 h) | P2 | §4 | **ICON-EU cannot be run-addressed for the backtest** (archive starts 2026-02-10); dynamical.org's ENS holds the 00 UTC run only, which arrived after the summer cutoff until 2025-10-01 (§4) |
| Fix the capacity denominator empirically: the winning EEM20 entry divided by the mean of registered capacity and the running maximum of observed output; the runner-up corrected capacity by hand from the rolling maximum, and a 5% correction in SE1 cut pinball loss by 10% | P3 | §5, Bellinguer 2020; Browell 2020 | competition data (dates anonymised, 2020 fleet) |
| Ceilings near 0.8 of capacity are normal for Sweden; downtime and low wind-speed diversity, not wakes, cap the fleet maximum | P3 | §6, Olauson 2018 | reanalysis-based, 2010s data |
| ECMWF IFS ENS archive as Zarr, 51 members, 100 m wind, init times from 2024-04-01 | P1 | §4, dynamical.org | **only the 00 UTC run, which reached the source bucket at 08:41 UTC before 2025-10-02 (after the 08:00 UTC summer cutoff) and at 07:41 UTC since**; the 12 and 18 UTC runs are in the bucket but not on dynamical.org; 3-hourly steps; ~20 km grid. Expect limited day-ahead gain (next row) |
| Ensemble spread may help less at day-ahead than hoped: the EEM20 runner-up found the ensemble mean sufficient, and weather-to-power uncertainty dominates up to about 2–3 days ahead (1.4–2.4 days on GB data) | P1 | §4 Dantas & Browell 2025, Cannon 2017; §5 Browell 2020 | gains concentrate in high-uncertainty situations (frontal passages), so test on the worst days rather than on average; Cannon's authors say operational systems could cross over earlier |
| Quantile-specific weights when combining two model families (boosted trees strong in the middle, GAM in the tails); peaks-over-threshold (GPD) tails; per-lead-hour recalibration | P1, P2 | §5 Browell 2020; §4 Dantas & Browell 2025 | tested on the four Swedish zones (Browell) and 73 GB farms (Dantas) |
| Open-Meteo **Single Runs API** — `run=` parameter, IFS HRES runs at 00/06/12/18 from 2024-03-14 | P2 | §4, Open-Meteo docs | fixes the vintage step for ECMWF only |
| Second-stage quantile regression on the first-stage quantiles, fitted on a separate block | P1 | §3 Lindberg 2024; §5 Lindberg 2023 | shown on one 6 MW park with a forest model, not on a zone with boosting |
| Beta-transformed pool as a two-parameter recalibration of a single predictive distribution, fitted on a held-out block | P1 | §3, Gneiting & Ranjan 2013; §4 Dantas & Browell 2025 | needs a distribution function (interpolate the quantiles); acts on the whole distribution, so a shortfall only at high output needs a per-regime fit; not shown on wind power in the source |
| Context-weighted or group-conditional conformal layer on the existing quantiles | P1 | §3, Moradi 2025; Gibbs 2024; Romano 2019 | exchangeability is violated by drift; Moradi tested solar only |
| More conservative hyperparameters for the outer quantiles; parametric tails | P1 | §2 Landry; §1 Sweeney | not tested on SE3 |
| Condition interval width on predicted level and a cut-out-risk indicator | P1 | §2, Pinson & Kariniotakis 2010 | single-farm, hand-built fuzzy rules |
| Coverage-by-output charts can mislead if binned by *realised* output | P1, EVAL | §9, Lerch 2017 | check how `coverage_by_output.png` bins |
| Flag or drop curtailed and non-reporting hours; normalise aggregates for units that report | P3, EVAL | §1, IEA guide 13.2.1–13.2.2 | needs a source of curtailment/reporting flags |
| German TSO "actual" PV is an upscaled estimate. A physical model using only register locations and capacities plus one fitted derating factor reached RMSE 4.2–4.9% of installed capacity against it (2015, April–October) and came within 0.4 points of two TSO day-ahead forecasts | SOL, EVAL | §10, Saint-Drenan 2017 | winter excluded; provenance of the TSO forecasts unclear; register currency differed by control area |
| Neighbourhood pseudo-ensemble from a deterministic 2.5 km run | P1 | §3, Molinder 2018 | icing study, two weeks of data; still under-dispersive. Analog ensembles are biased low in the right tail when the archive is short (Alessandrini 2019) |
| ENTSO-E `A03` step-curve encoding under-reports if parsed naively | P3 | §6, Nicolaysen 2026 | entsoe-py 0.7.11 already forward-fills it, so probably handled (not tested on SE3 data); single-author preprint |
| Uncalibrated QRF/boosted-tree quantiles were the worst-reliability approach on all four SE zones regardless of model flexibility; a conformal calibration layer (CQR/SCPS) beat every uncalibrated baseline, and a logit-transformed nonconformity score (target mapped through logit before scoring) improved efficiency over the plain residual score | P1 | §5, Jonkers 2024 | competition data, anonymised dates; logit trick only tested on a [0,1]-bounded load-factor target |

**Two headline results to treat with care.** Kean & O'Sullivan (2026) report beating the ENTSO-E
day-ahead forecasts by about 26%, but their weather inputs are historical values "used as a
proxy for forecasts", not archived forecasts (§5). That comparison is not evidence that the TSO
can be beaten from real NWP, which supports the caution in your README. Wanek (2026) uses real
NWP for its headline German numbers, but the model is trained on reanalysis and the real-NWP test
covers about four winter months (§10). Neither report speaks to your vintage problem.

**Results that corroborate what the README already found.** Lindberg et al. (2024) used only
the MEPS control member because MEPS's ensemble size was inconsistent over their period, the
same publication-history problem `reports/meps_archive.md` hit. Meisenbacher et al. (2025) found
plain power-curve models beat deep autoregressive models when shutdowns are irregular, and Wanek
(2026) concludes that NWP source quality mattered as much as model complexity, in line with
"physics gets you most of the way". The EEM20 papers, which use the same four Swedish zones,
found the same capacity-register unreliability you did (§5, §6).

---

## 1. Foundations and reviews

### Probabilistic energy forecasting: Global Energy Forecasting Competition 2014 and beyond
Hong, Pinson, Fan, Zareipour, Troccoli, Hyndman · Int. J. Forecasting 32(3), 2016 ·
[10.1016/j.ijforecast.2016.02.001](https://doi.org/10.1016/j.ijforecast.2016.02.001) · *read: metadata + search excerpt*

Editorial for the GEFCom2014 special section; the wind and solar tracks were scored with the
pinball loss on a grid of quantiles.
- Quantile-based scoring with rolling out-of-sample weeks became the reference way to compare probabilistic VRE models.
- The competition fixed the information set per forecast issue, which is the discipline your information-age test enforces.
- → GEFCom2014 wind entries are a ready-made list of what worked for boosted-tree quantile models (see Landry, §2).

### The future of forecasting for renewable energy
Sweeney, Bessa, Browell, Pinson · WIREs Energy Environ. 9(2), 2020 ·
[10.1002/wene.365](https://doi.org/10.1002/wene.365) · *read: abstract + full text skimmed*
PDF: `research/data/papers/sweeney2019_future-of-forecasting.pdf`

Overview of wind and solar forecasting from minutes to days ahead, then a look at where it is heading.
- Future products need probabilistic information, delivered in a form tailored to the end user's decision problem and risk constraints.
- Quantile regression is now the leading approach for univariate densities, but parametric models are still preferred for the tails, where quantile regression has high variance.
- The Analog Ensemble builds an ensemble from the past observations whose NWP forecasts best match the current one, and has been used for both wind and solar (it cites Yang, Astitha, Delle Monache and Alessandrini, 2018).
- Multivariate forecasts (several lead times or locations) are typically built from univariate forecasts plus a copula (Tastu, Pinson, Madsen, 2015).
- Notes a mismatch between licensed and true rated PV power for behind-the-meter systems.
- → Tail behaviour is exactly where your ranges are too narrow, so a parametric tail beyond the outer quantiles is worth testing.
- → The Analog Ensemble is a candidate spread substitute when no archived ensemble exists (compare the `query similar-days` tool in grid-signals).
- → The behind-the-meter point is the Swedish rooftop-solar problem your README mentions.

### Probabilistic forecasting
Gneiting, Katzfuss · Annu. Rev. Stat. Appl. 1, 2014 ·
[10.1146/annurev-statistics-062713-085831](https://doi.org/10.1146/annurev-statistics-062713-085831) · *read: abstract (PDF added, not read further)*
PDF: `research/data/papers/gneiting2014_probabilistic-forecasting.pdf`

Statistical foundations of probabilistic forecasting.
- Central principle: maximise the sharpness of the predictive distribution subject to calibration, given the available information.
- Probabilistic calibration is checked with PIT histograms; the CRPS assesses calibration and sharpness together.
- → Frames problem 1 precisely: the ranges are sharp but not calibrated, so calibration comes first.

### IEA Wind Recommended Practice for the Implementation of Renewable Energy Forecasting Solutions
IEA Wind TCP Task 36/51 (Möhrlen, Zack, Giebel et al.) · Elsevier, 2023 ·
[10.1016/C2021-0-03549-5](https://doi.org/10.1016/C2021-0-03549-5) · *read: chapters 12–14 selectively (390-page book)*
PDF: `research/data/papers/mohrlen2023_iea-recommended-practice.pdf`

Industry guidance on choosing, trialling and evaluating forecast solutions; the evaluation part is the useful one here.
- **12.1.1** The evaluation sample must represent all significant modes of variation (seasons, weather regimes), and every solution must be scored on exactly the same data. If a source is missing on hard days its score is flattered.
- **13.2.1** Raw production contains non-weather reductions (turbine failures, maintenance, curtailment, environmental limits). Decide whether the target is actual or available power; if available, drop curtailed data unless curtailment is itself forecast.
- **13.2.2** When aggregating over zones, non-reporting units and communication failures must be identified and the aggregate normalised accordingly. Also say whether hourly values are averages of higher-resolution data or instantaneous values at the start of the hour.
- On storms, the grid-critical quantity is the share of farms in high-speed shutdown; grid-related down-regulation is a separate mechanism. Extreme events beyond cut-out need probability characterisation and an extreme-event analysis.
- Chapter 14 covers probabilistic verification: Brier scores, rank histograms, reliability diagrams, CRPS and relative operating characteristic.
- → 13.2.2 reads like a description of problem 3: the capacity denominator should be the capacity of units that actually report, if that can be identified.
- → The averages-versus-instantaneous distinction matters for the hourly-to-15-minute move.
- → 12.1.1 supports keeping the frozen hold-out and scoring the TSO forecast only on days where all series exist.

---

## 2. Quantile and tree-based models

### Quantile regression forests
Meinshausen · J. Mach. Learn. Res. 7, 2006 · [jmlr.org/papers/v7/meinshausen06a.html](https://jmlr.org/papers/v7/meinshausen06a.html) (no DOI) · *read: abstract (PDF added, not read further)*
PDF: `research/data/papers/meinshausen2006_quantile-regression-forests.pdf`

Random forests that keep leaf observations so any quantile of the conditional distribution can be read off.
- One fitted model gives all quantiles, and they cannot cross.
- → A useful cross-check against LightGBM quantile models; it is the model the Swedish SE3 studies used (§3, §5).

### Probabilistic gradient boosting machines for GEFCom2014 wind forecasting
Landry, Erlinger, Patschke, Varrichio · Int. J. Forecasting 32(3), 2016 ·
[10.1016/j.ijforecast.2016.02.002](https://doi.org/10.1016/j.ijforecast.2016.02.002) · *read: full text (6 pages)*
PDF: `research/data/papers/landry2016_gefcom-wind-gbm.pdf`

The winning entry of the GEFCom2014 wind track (first overall, first in 11 of 12 tasks): independent quantile-loss gradient boosting per zone and quantile.
- One model per quantile (99 in the competition); the authors found that nine quantiles approximated the full quantile loss closely and cut run time.
- The outer quantiles (0.01–0.15 and 0.85–0.99) used more conservative hyperparameters than the middle range (0.16–0.84), chosen by cross-validation.
- The most important input was "bidirectional lagged" 100 m wind-energy forecasts, i.e. the NWP series smoothed over neighbouring hours to absorb timing errors.
- Two-layer scheme: out-of-sample median predictions from a first layer feed a second layer, which gained from a neighbouring zone's median in four of ten zones; contiguous-block stratified k-fold kept the stacking free of leakage.
- → Tail-specific regularisation is a cheap experiment for the high-wind under-coverage.
- → Check that your feature set has time-shifted NWP features and a neighbour-zone (SE2, SE4, NO, FI) median layer.
- 2014 competition data with provided NWP, so it says nothing about forecast vintage or calibration on held-out data beyond the score.

### GEFCom 2014: Probabilistic solar and wind power forecasting using a generalized additive tree ensemble approach
Nagy, Barta, Kazi, Borbély, Simon · Int. J. Forecasting 32(3), 2016 ·
[10.1016/j.ijforecast.2015.11.013](https://doi.org/10.1016/j.ijforecast.2015.11.013) · *read: full text (7 pages)*
PDF: `research/data/papers/nagy2016_gefcom-gat-ensemble.pdf`

Second place overall in both the solar and the wind track of GEFCom2014: a vote of a quantile regression forest and a stacked model (a random forest's point forecast fed to quantile-loss gradient boosting), 99 quantiles per zone. The text describes voting, bagging, boosting and stacking of trees; I found no separate additive-model component despite the title.
- Raw quantiles from boosting can cross, so isotonic regression forces them to be non-decreasing. The authors say this improved accuracy, and that nobody compared it with simply sorting the quantiles.
- Voting was most useful for averaging quantile forecasts of different models. In the last stage the stack alone beat the vote on one zone because the forest's error distribution had a much higher mode.
- Wind inputs: 10 and 100 m wind components, magnitudes at 10/50/100 m, angles binned to 45°, the 100 m minus 10 m difference, and copies shifted up to three hours either way. Letting the trees choose from all features beat hand-made zone groupings.
- Solar inputs: total column liquid and ice water, cloud cover, humidity, temperature, wind, decumulated radiation and precipitation, plus hour, day of year and month.
- Manual outlier filtering looked good for the first weeks, then gave inconclusive cross-validation and leaderboard results and was dropped.
- Row-based cross-validation misled them: it favoured fewer features while the leaderboard did not; they later validated by day.
- Fitting 99 separate models was slow; they suggest a boosting scheme that optimises the pinball loss over all quantiles at once.
- → Check how quantile crossing is handled in your pipeline; sorting is the cheap alternative they never tested.
- → Supports blocked splits for validation (also Landry above).
- → Solar feature list is a starting point for the German track.
- Competition data with provided NWP, so nothing on forecast vintage or drift.

### Conditional prediction intervals of wind power generation
Pinson, Kariniotakis · IEEE Trans. Power Syst. 25(4), 2010 ·
[10.1109/tpwrs.2010.2045774](https://doi.org/10.1109/tpwrs.2010.2045774) · *read: abstract + method sections skimmed*
PDF: `research/data/papers/pinson2010_conditional-prediction-intervals.pdf`

"Adapted resampling": nonparametric intervals from the empirical distribution of past errors, conditioned through a fuzzy inference model on the forecast level (low, medium, high power) and on cut-off risk (forecast wind speed near cut-out).
- Time-adaptive weighting favours recent errors, motivated by non-stationarity.
- Compared with time-adaptive quantile regression and climatology on a Danish onshore farm; discusses operational use on many farms in Europe and Australia.
- Simultaneous intervals at several nominal levels give a full predictive distribution.
- → Direct precedent for conditioning uncertainty on the predicted level plus a cut-out-risk indicator, which is what your high-wind under-coverage calls for. An analogue for zone level is the share of your eight points forecast near cut-out.
- Single-farm data; the fuzzy rules are hand-designed.

### On-line assessment of prediction risk for wind power production forecasts
Pinson, Kariniotakis · Wind Energy 7(2), 2004 ·
[10.1002/we.114](https://doi.org/10.1002/we.114) · *read: abstract + introduction*
PDF: `research/data/papers/pinson2004_prediction-risk-index.pdf`

Resampling-based confidence intervals with no distributional assumption on errors, refined by a "meteo-risk index" (MRI).
- Errors are classified with fuzzy sets to respect the non-linear power curve and the cut-off effect.
- The MRI is built from NWP ensembles and reflects the stability of the weather regime; the abstract reports a linear relation between it and the resulting prediction error.
- Intervals are narrowed in stable weather; the index is also offered as a warning signal for operators.
- → Your worst day was "confidently mistaken" with an ordinary-width band. A spread-based risk index is the classical remedy.
- → Uses a true ensemble; your multi-model spread is only a rough substitute, so test whether it predicts error before building on it.

---

## 3. Calibration, spread and conformal methods (P1)

### Quantifying the value of probabilistic forecasts when trading renewable hybrid power parks in day-ahead markets: A Nordic case study
Lindberg, Zhu, Widén · Renewable Energy 237, 2024 ·
[10.1016/j.renene.2024.121617](https://doi.org/10.1016/j.renene.2024.121617) · *read: full text (abstract, data and methods sections)*
PDF: `research/data/papers/lindberg2024_value-of-probabilistic-hpp.pdf`

Swedish (SE3) wind+PV park, Nord Pool day-ahead, almost two years of data.
- Quantile regression forest (QRF) alone had insufficient reliability, so its quantiles were recalibrated with a second-stage quantile regression on the QRF output (19 nominal levels), checked with PIT histograms.
- Only the MEPS control member was used because MEPS had an inconsistent number of ensemble members over the study period.
- Day-ahead inputs came from the 00 UTC run at lead times 24–48 h, with one model per lead hour.
- A climatology-style multivariate benchmark had CRPS about 100% worse than the deterministic and QRF+QR models, yet the more advanced probabilistic model did not beat that simple benchmark by a significant margin in unit profit.
- → A two-stage "quantile model then recalibrate" recipe is a direct, low-cost try for P1 on the existing LightGBM output.
- → Independent confirmation that MEPS membership is unreliable as a feature.
- → Park-level, one site, models trained on 2016–2018 data: use as method evidence, not as a benchmark number.

### Conformalized quantile regression
Romano, Patterson, Candès · NeurIPS 2019 · arXiv
[10.48550/arXiv.1905.03222](https://doi.org/10.48550/arXiv.1905.03222) · *read: method section checked (PDF added, not read further)*
PDF: `research/data/papers/romano2019_cqr.pdf`

Widens or narrows a quantile-regression band by a margin estimated on held-out data, giving finite-sample marginal coverage.
- The conformity score is E_i = max{lower_i − y_i, y_i − upper_i} on a calibration set, and the band is adjusted by the appropriate quantile of those scores; it can widen or narrow the band.
- Keeps the adaptivity of quantile regression and adds a coverage guarantee.
- → Turns the observed 74% into an 80% target by construction, but only on average: the high-wind shortfall needs the group-conditional variants below.
- → The guarantee assumes exchangeability; time series drift, so the calibration set should be the most recent stretch, not random.

### Conformal Prediction: A Gentle Introduction
Angelopoulos, Bates · Found. Trends Mach. Learn. 16(4), 2023 ·
[10.1561/2200000101](https://doi.org/10.1561/2200000101) · *read: metadata only*

Practical tutorial with recipes for regression intervals.
- Good single reference for implementing split conformal and understanding what "coverage" it does and does not promise.

### The limits of distribution-free conditional predictive inference
Barber, Candès, Ramdas, Tibshirani · Inf. Inference 10(2), 2021 ·
[10.1093/imaiai/iaaa017](https://doi.org/10.1093/imaiai/iaaa017) · *read: abstract + introduction*
PDF: `research/data/papers/barber2020_limits-conditional-inference.pdf`

Shows that exact coverage conditional on the covariates is impossible without assumptions, other than with trivial intervals.
- → Don't aim for "80% at every output level"; aim for coverage within pre-chosen groups (predicted-level bins, season).

### Conformal prediction with conditional guarantees
Gibbs, Cherian, Candès · arXiv 2023 (v4, 2024) ·
[10.48550/arXiv.2305.12616](https://doi.org/10.48550/arXiv.2305.12616) · *read: abstract, introduction, group-coverage sections*
PDF: `research/data/papers/gibbs2024_conformal-conditional-guarantees.pdf`

Extends split conformal to exact finite-sample coverage over any finite-dimensional class of covariate shifts, for example over each of a collection of groups.
- Groups may overlap, unlike Mondrian conformal prediction, which needs a partition. A randomised version gives exact coverage; the unrandomised version is conservative.
- Fits into existing split-conformal pipelines; a Python package, `conditionalconformal`, is on PyPI.
- Assumes exchangeable data.
- → Lets you require coverage at once for "predicted output in the top decile", "winter" and "lead hour 34 or later".
- → Your two years drift, so validate on a rolling hold-out rather than trusting the guarantee.

### Enhanced renewable energy forecasting using context-aware conformal prediction
Moradi, Tanneau, Zandehshahvar, Van Hentenryck · arXiv 2025 (v2, 2026) ·
[10.48550/arXiv.2510.15780](https://doi.org/10.48550/arXiv.2510.15780) · *read: full text (methods and results skimmed)*
PDF: `research/data/papers/moradi2025_context-aware-conformal.pdf`

Weighted split conformal on top of conformalized quantile regression: calibration scores are weighted by the similarity of their context (temporal features plus forecast weather) to the target hour. Day-ahead solar for MISO, ERCOT and SPP.
- A nearest-neighbour weighting (KD-tree retrieval) performed best; the covariate groups used are re-selected over a rolling recalibration window.
- Base forecasts were miscalibrated: system-level coverage at a 90% target rose from 77.5% to 90.1% (ERCOT), site-level from 47.9% to 90.1%, with equal or narrower intervals.
- The coverage-gap bound depends on the weighted total-variation distance between the calibration and target distributions, which is why similarity weights help.
- → The base miscalibration resembles yours (74% against 80%), and it is a post-hoc layer on existing quantiles. A test: context = predicted output, wind regime, month, lead hour and multi-model spread.
- Solar only, US systems; no independent replication.

### Conformal prediction beyond exchangeability
Barber, Candès, Ramdas, Tibshirani · Ann. Stat. 51(2), 2023 ·
[10.1214/23-aos2276](https://doi.org/10.1214/23-aos2276) · *read: metadata only*

Weighted conformal prediction for non-exchangeable data such as time series.
- Down-weighting old residuals keeps coverage approximately valid under drift, with a bound depending on how much the distribution moved.

### Adaptive conformal inference under distribution shift
Gibbs, Candès · NeurIPS 2021 · arXiv
[10.48550/arXiv.2106.00170](https://doi.org/10.48550/arXiv.2106.00170) · *read: metadata only*

Online update of the target miscoverage level so long-run coverage holds despite shifts.
- → Relevant to the live trial, where the fleet and the weather model change over time.

### Probabilistic forecasts of wind speed: Ensemble model output statistics by using heteroscedastic censored regression
Thorarinsdottir, Gneiting · J. R. Stat. Soc. A 173(2), 2010 ·
[10.1111/j.1467-985x.2009.00616.x](https://doi.org/10.1111/j.1467-985x.2009.00616.x) · *read: search excerpt*

Predictive distribution whose variance is a function of ensemble variance; the fitted coefficients measure the spread–skill relationship.
- If spread and skill are unrelated the coefficient is negligible, so the method tells you whether a spread feature is worth having.
- → Use as a test: does multi-model spread predict error on your data before building it into the model?

### Calibrated probabilistic forecasting using ensemble model output statistics and minimum CRPS estimation (EMOS)
Gneiting, Raftery, Westveld, Goldman · Mon. Weather Rev. 133(5), 2005 ·
[10.1175/mwr2904.1](https://doi.org/10.1175/mwr2904.1) · *read: metadata only*

Introduces EMOS: a regression-based calibration of raw ensembles fitted by minimising CRPS.
- Raw ensembles are typically under-dispersive; a small fitted correction repairs them.

### Combining probability forecasts
Ranjan, Gneiting · J. R. Stat. Soc. B 72(1), 2010 ·
[10.1111/j.1467-9868.2009.00726.x](https://doi.org/10.1111/j.1467-9868.2009.00726.x) · *read: full text*
PDF: `research/data/papers/ranjan2010_combining-probability-forecasts.pdf`

Shows that averaging probability forecasts (the linear opinion pool) yields something uncalibrated and unsharp, and repairs it by composing the pool with a beta distribution function.
- Theorem 1: a weighted average of two or more distinct, calibrated forecasts is not calibrated, and on average sits closer to the climatological forecast than its recalibrated version, which scores better under every strictly proper scoring rule. It is a finite-sample result that assumes nothing about how the sources depend on each other.
- The pooled forecast is therefore under-confident, in the authors' words closer to the climatological forecast than necessary.
- The beta-transformed linear pool (BLP) fits the weights and the beta shape parameters (α, β) by maximum likelihood; it adds at most two, typically one, parameters to the linear pool. In their second, asymmetric simulation the symmetric version (α = β) stayed miscalibrated and the general one was calibrated.
- Case study: probability-of-precipitation forecasts for 29 US cities from statistical and National Weather Service sources; the BLP forecast was calibrated and outscored both sources and the linear pools.
- More complex aggregation (copulas, for example) risks overfitting for likely small gains.
- → The paper treats binary events; the extension to predictive distributions is Gneiting & Ranjan (2013), next entry, and Dantas & Browell (§4) use it for wind.
- → Pooling widens forecasts, so on its own it would ease rather than cause over-confidence when the pooled models are over-confident. It becomes relevant if you combine model families (ECMWF- and GFS-driven models, say) by averaging probabilities. Averaging quantiles is a different operation, which neither paper treats.

### Combining predictive distributions
Gneiting, Ranjan · Electron. J. Stat. 7, 2013 ·
[10.1214/13-ejs823](https://doi.org/10.1214/13-ejs823) · *read: full text (abstract, theory and discussion; simulation and data examples skimmed)*
PDF: `research/data/papers/gneiting2013_combining-predictive-distributions.pdf`

Extends Ranjan & Gneiting (2010) from binary events to predictive distributions of a real-valued quantity, judging aggregation methods by calibration and dispersion through the probability integral transform (PIT).
- Theorem 3.1: a linear pool of two or more distinct forecasts is at least as dispersed as its least dispersed component, and if the components are calibrated the pool is over-dispersed. Pooling therefore helps when the components are under-dispersed (over-confident), which the authors say explains the success of linear pooling, and hurts when they are already calibrated.
- Spread-adjusted linear pool (SLP): shift each component to its median, scale its spread by one common factor c (below 1 for calibrated or over-dispersed components, 1 or more for under-dispersed ones), then pool. It is not flexibly dispersive: when component means are far apart the combined forecast stays too narrow whatever the weights and c.
- Beta-transformed linear pool (BLP): apply a beta distribution function (parameters α, β) to the pooled distribution function. It is flexibly dispersive, since the variance of the PIT can take any value between 0 and 1/4. Weights and (α, β) are fitted by maximising the log score on training data.
- SLP and BLP can also be used to correct the calibration and dispersion of a single predictive distribution.
- Parsimony matters: with scarce training data the plain linear pool can be the better choice despite its flaws; with plenty of data, nonlinear pools gain.
- Case studies are S&P 500 returns and daily maximum temperature at Seattle-Tacoma airport.
- → The single-model use is the direct P1 tool: fit a BLP to your model's predictive distribution on a held-out block. Two parameters can widen or narrow it, but it acts on the whole distribution, so a shortfall confined to high output needs a separate fit per output regime or the group-conditional conformal methods above.
- → It needs a distribution function, so a set of quantiles has to be interpolated into one first. The PIT histogram is the diagnostic that says which way to go.
- Not tested on wind power here; Dantas & Browell (§4) is the wind use.

### Evaluating ensemble post-processing for wind power forecasts
Phipps, Lerch, Andersson, Mikut, Hagenmeyer, Ludwig · Wind Energy 25(8), 2022 ·
[10.1002/we.2736](https://doi.org/10.1002/we.2736) · *read: abstract*

Compares four EMOS strategies: none, post-process weather members, post-process power members, or both.
- Post-processing the final power ensemble works best; post-processing only the weather ensemble does not necessarily help.
- Only EMOS was tested, so it says nothing about quantile forests or boosting.
- → Consistent with your rule to transform members first and summarise after; calibrate at the power level.

### Neural networks for postprocessing ensemble weather forecasts
Rasp, Lerch · Mon. Weather Rev. 146(11), 2018 ·
[10.1175/mwr-d-18-0187.1](https://doi.org/10.1175/mwr-d-18-0187.1) · *read: metadata only*

Network that outputs distribution parameters, trained on CRPS, with ensemble mean and spread as inputs.
- → Optional later step: a CRPS-trained distributional head as an alternative to per-quantile boosting.

### Ensemble-based probabilistic forecasting at Horns Rev
Pinson, Madsen · Wind Energy 12(2), 2009 · online 2008 ·
[10.1002/we.309](https://doi.org/10.1002/we.309) · *read: abstract + introduction skim*
PDF: `research/data/papers/pinson2009_ensemble-forecasting-horns-rev.pdf`

Complete ensemble-to-predictive-distribution chain for one offshore farm over about a year.
- Ensemble meteorological forecasts are converted to power with an adaptively estimated local-polynomial power curve; the power ensemble is then turned into a predictive distribution by adaptive kernel dressing whose shape comes from a mean–variance model with recursively estimated parameters, fitted to maximise overall skill.
- States that ensemble forecasts of wind power are not reliable in the probabilistic sense and must be recalibrated; the result is more reliable than the raw ensemble while keeping its resolution.
- → Same "convert members to power first, then dress and recalibrate" order as Phipps et al. (2022); recursive estimation is one way to track drift.
- One farm, one year, 2000s NWP.

### Probabilistic weather prediction with an analog ensemble
Delle Monache, Eckel, Rife, Nagarajan, Searight · Mon. Weather Rev. 141(10), 2013 ·
[10.1175/mwr-d-12-00281.1](https://doi.org/10.1175/mwr-d-12-00281.1) · *read: full text (abstract, data, method, verification and discussion)*
PDF: `research/data/papers/delle-monache2013_analog-ensemble.pdf`

The original analog ensemble (AnEn): the predictive distribution at a location and lead time is the set of observations that accompanied the past forecasts of the same model, at the same lead time, most similar to today's deterministic forecast. Tested on 10 m wind and 2 m temperature at 550 US stations, 0–48 h ahead, 23 April – 31 July 2011, from a 15 km deterministic model with a 12–15-month archive, against the 21-member Canadian REPS raw and post-processed with EMOS and logistic regression.
- The raw ensemble was strongly under-dispersive for wind, with observations often above every member and a negative bias, the same over-confidence as your P1. AnEn had a near-uniform rank histogram, slight over-spread and a good spread–skill relationship, so its spread grew when errors did.
- Skill and value were equal to or better than logistic regression and EMOS, and for wind above 10 m/s AnEn was better than both.
- A 9-month archive did worse than the full one, and the authors expect multi-year archives to help AnEn more than the regression methods.
- The method needs a long history of forecasts from a frozen modelling system to find analogs; the authors count this as its main cost.
- → With roughly two years of vintage-consistent archives and periodic IFS upgrades, the archive is the constraint, and Alessandrini et al. (below) show the right-tail bias that follows. As a spread feature rather than the predictive distribution it is cheap to test.
- US station winds and temperature, not power.

### Improving the analog ensemble wind speed forecasts for rare events
Alessandrini, Sperati, Delle Monache · Mon. Weather Rev. 147(7), 2019 ·
[10.1175/mwr-d-19-0006.1](https://doi.org/10.1175/mwr-d-19-0006.1) · *read: abstract + introduction*
PDF: `research/data/papers/alessandrini2019_analog-ensemble-rare-events.pdf`

The analog ensemble (AnEn) forms its members from observations that coincided with the past forecasts most similar to the current one, at the same lead time.
- The standard AnEn has a conditional negative bias for events in the right tail of the wind-speed distribution, worst when the training archive is short and the event is rare.
- A new bias correction, tested on more than 500 US stations, reduces the underestimation and improves probabilistic skill for wind above 10 m/s.
- → A caution for the analog-ensemble idea in §1: with about two years of archived forecasts it would under-predict high-wind hours, exactly where you are under-covered. It needs the correction, or should be used as a spread feature rather than as the predictive distribution.
- → Like any AnEn it needs an archive of past forecasts at the same lead time, so it inherits the vintage constraint.
- US station wind speeds, not zonal power.

### Probabilistic forecasting of wind power production losses in cold climates: a case study
Molinder, Körnich, Olsson, Bergström, Sjöblom · Wind Energy Sci. 3, 2018 ·
[10.5194/wes-3-667-2018](https://doi.org/10.5194/wes-3-667-2018) · *read: abstract + results*

Swedish icing losses from an 11-member 2.5 km ensemble (HarmonEPS) and a neighbourhood of 25 grid points, over two weeks.
- Ensemble + neighbourhood cut production-loss error from 26% to 21%; spread–skill correlation rose from about 0.3 (neighbourhood only) to about 0.7.
- Forecasts stayed under-dispersive: actual error exceeded predicted spread.
- → With no usable ensemble, the spread of nearby grid points in a deterministic 2.5 km run is a candidate pseudo-ensemble for MEPS-det, which you already extract.
- → Two weeks and an icing target, so evidence of principle only.
- → The follow-up quantile-forest icing paper (2021) and a 2026 cold-climate review are parked in §13; revisit them only if icing is confirmed.

---

## 4. Weather data: run addressing, vintage and ensemble archives (P1, P2)

### Which models can be run-addressed for the backtest window?
Compiled from the entries below; backtest window 2024-09-02 to 2026-03-01.

| model | run-addressed source | covers the window? |
|---|---|---|
| ECMWF IFS (HRES, 9 km) | Open-Meteo Single Runs: 00/06/12/18 UTC runs from 2024-03-14 | yes |
| ECMWF IFS ENS (0.25°, 51 members) | dynamical.org: **00 UTC only**, from 2024-04-01, 3-hourly to 144 h. The source bucket `s3://ecmwf-forecasts` also holds the 12 UTC and 18 UTC runs | yes, but the 00 UTC run reached the bucket at about 08:41 UTC before 2025-10-02 and 07:41 UTC after, so it misses the summer cutoff in the first period (arrival-times entry below) |
| NOAA GFS (0.25°) | dynamical.org: every 6 h from 2021-05-01, hourly to 120 h, 10/80/100 m wind | yes |
| DWD ICON-EU (7 km) | dynamical.org: from 2026-02-10 only, because DWD keeps a short rolling window and archiving began in March 2026; Open-Meteo Single Runs: from 2026-04-02 | **no** |
| MEPS (2.5 km) | MET Norway THREDDS (see `reports/meps_archive.md`) | deterministic yes; the 30-member ensemble ends 2024-12-10 |

So ICON-EU, one of your three pinned models, cannot be given run-addressing retroactively; it would have to stay on whole-day offsets or be dropped from the vintage-fixed track.

### Open-Meteo Single Runs API
Open-Meteo documentation · [open-meteo.com/en/docs/single-runs-api](https://open-meteo.com/en/docs/single-runs-api) · *read: docs page*

Returns the full horizon of one archived model run, selected with a required `run=YYYY-MM-DDTHH:MM` parameter.
- ECMWF IFS HRES (9 km) individual runs at 00/06/12/18 UTC archived from 2024-03-14; most other models only from 2026-04-02.
- The docs warn that initialisation time differs from public availability (about 4–6 h for global models).
- → Would give a run-addressed IFS and remove the lead-hour-34 step for that model without the MEPS download. Your reports record that a `*_previous_run1` parameter was rejected, but do not mention this endpoint.
- → This endpoint covers only IFS over the backtest window. GFS is covered by dynamical.org and ICON-EU by nothing I found (see the table at the top of this section). Also confirm the 9 km HRES matches the 0.25° `ecmwf_ifs025` you pinned before swapping it in.
- → Pricing and free-tier limits were not visible on the page; check before planning a two-year pull.

### Open-Meteo Previous Runs API and maintainer discussion #1023
Open-Meteo documentation · [Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api) · [discussion](https://github.com/open-meteo/open-meteo/discussions/1023) · *read: docs page + discussion*

Fixed lead-time offsets (`_previous_day1` … `_previous_day7`); most models archived from January 2024.
- The Historical Forecast API instead stitches the first hours of every run, so it is not what a day-ahead model sees.
- The maintainer notes processing delay (about 5 h 20 min for ECMWF IFS) is folded into the offset, and that combining offsets from several runs still worked well for day-ahead ML.
- → Confirms your finding that this API cannot be addressed by run; supports the information-age bookkeeping you already do.

### ECMWF IFS ENS 15-day forecast (Zarr archive)
dynamical.org · [catalog page](https://dynamical.org/catalog/ecmwf-ifs-ens-forecast-15-day-0-25-degree/) · [STAC collection](https://stac.dynamical.org/ecmwf-ifs-ens-forecast-15-day-0-25-degree/collection.json) · [AWS registry](https://registry.opendata.aws/dynamical-ecmwf-ifs-ens/) · *read: catalog page, STAC metadata, dynamical.org `prompt.md`, `llms.txt` and migration guide, ECMWF dissemination schedule*

51-member ECMWF ensemble (1 control + 50 perturbed) at 0.25°, built from ECMWF Open Data on the AWS registry; init times 2024-04-01 to present, **00 UTC only**, one run per day; CC BY 4.0.
- Steps: 85 in total, 3-hourly to 144 h then 6-hourly to 360 h.
- Variables include `wind_u_100m` and `wind_v_100m`. Documented gaps: `wind_gust_10m` and the precipitation-type field are NaN before 2024-11-13, and total cloud cover is NaN before 2025-11-21. All 51 members are present throughout. 100 m wind is not listed as gapped.
- Datasets are versioned (this one is v0.1.0) and the `prompt.md` and `llms.txt` guidance says to resolve the asset location from the STAC catalog each time and not hard-code buckets or versions, because they change when a dataset is reprocessed. Access is via `dynamical_catalog.open(...)` (Python 3.12+, Icechunk 2.0); the legacy `data.dynamical.org` service is being retired from 2026-09-30.
- No latency figure is documented on the catalog page; measured arrival times of the source files are in the next entry.
- ECMWF's real-time schedule puts 00 UTC ENS steps to 144 h at 06:40–07:04 UTC and steps to 360 h by 07:40 UTC. ECMWF says its open data are released at the end of that schedule; measured arrival in the bucket is in the next entry.
- → This is the instrument `meps_archive.md` guessed at, and it spans the whole window with no member gaps.
- → Timing: your cutoff of 10:00 market time is 08:00 UTC in summer (CEST) and 09:00 UTC in winter (CET). The measured arrival of the 00 UTC run (next entry) misses the summer cutoff before 2025-10-02 and leaves about 19 minutes after it, before dynamical.org's own processing delay. Measure that delay by logging when each new `init_time` appears.
- → Steps are 3-hourly, so hourly values need interpolation. Thorarinsdottir et al. (2019) used a spline constrained to be non-negative for wind, and interpolation over the clear-sky index for solar irradiance.
- → Given Dantas & Browell (2025) and Browell et al. (2020), do not expect the spread to fix over-confidence on average; test it on the worst days.

### Arrival times of ECMWF open data: dynamical.org status page and bucket timestamps
Pipeline status page text pasted by you on 2026-09-21 (times shown UTC+2) · public bucket `s3://ecmwf-forecasts` · *read: the pasted status page; bucket listings and `Last-Modified` headers, sampled by me on 2026-09-21*

Two independent views of when ECMWF's open-data files appear. The status page is dynamical.org's monitor of the same bucket (259 samples for the 12-hourly IFS ENS product, about four months; 1,411 for AIFS). For history I sent HEAD requests for the step-48 h (00 UTC run), step-60 h (12 UTC) and step-54 h (18 UTC) ensemble files on 61 dates, one every nine days from 2024-09-02 to 2026-03-01; an object's timestamp is when it appeared. I did not cover every day.
- **Status page, 00 UTC IFS ENS 0.25° (recent runs), hours after init at median / 95th / 99th percentile:** steps to 1 d 7h40 / 7h42 / 7h45; to 3 d 7h43 / 7h47 / 7h55; to 6 d 7h46 / 7h54 / 8h17; to 15 d 7h50 / 8h08 / 9h05. Its "delayed past" alarm sits at 8h02 for the 3-day group. In UTC the 00 UTC run's 3-day group is therefore complete at about 07:43, and at 07:55 in the worst 1%.
- **Bucket timestamps agree, and add history:** for the 00 UTC run the step-48 h file appeared **8.68–8.73 h after init (about 08:41 UTC) on every date sampled from 2024-09-02 to 2025-10-01, and 7.68 h (07:41 UTC) on every date from 2025-10-02 to at least 2026-09-01.** The one-hour step falls exactly between 2025-10-01 and 2025-10-02 (checked day by day); I did not identify the cause. Spread within each period was under 0.1 h.
- **12 UTC run** (step 60 h): median 8.69 h after init in the sampled dates, minimum 7.68 h (about 20:41 UTC the same evening before the change). **18 UTC run** (step 54 h): median 8.09 h, minimum 7.08 h (about 02:05 UTC the next morning before the change).
- The bucket holds 12 UTC and 18 UTC ensemble runs at 0.25° as GRIB2 throughout the window (a 2024 12 UTC step-0 file was about 4 GB, with `.index` files for byte-range access), though dynamical.org republishes only the 00 UTC run. Whether the ensemble carries 100 m wind here should follow from dynamical.org's dataset having it, but I did not open a GRIB file.
- For the deterministic model, the open-data HRES step-48 h file arrived 8.57 h after init before the change and 7.57 h after it (19 sampled dates); the 06/18 UTC short-cutoff runs 7.45 h and 6.45 h. Open-Meteo may receive HRES by another route, so this does not tell you when its Single Runs appear.
- → Against your cutoff (10:00 local, 08:00 UTC in summer, 09:00 UTC in winter): before 2025-10-02 the 00 UTC ensemble was **not in the bucket in time in summer** (08:41 UTC) and had about 19 minutes' margin in winter. Since then it has about 19 minutes' margin in summer at the median (5 at the 99th percentile for the 3-day group) and more than an hour in winter. All of this is before dynamical.org's own processing delay, which is still unmeasured.
- → A backtest that respects the cutoff cannot use the same-day 00 UTC ensemble in summer before 2025-10-02. The available vintages for the next delivery day are the previous day's 12 UTC run (leads about 34–58 h), 18 UTC run (28–52 h) or 00 UTC run (46–70 h), against 22–46 h for the same-day 00 UTC run. Only the 00 UTC runs are on dynamical.org; the 12 and 18 UTC runs would have to come from the bucket.
- → Use the status page's `1d` and `3d` groups as the relevant ones only if they mean "steps up to that lead"; I assumed so.

### NOAA GFS forecast and DWD ICON-EU forecast on dynamical.org
dynamical.org · [GFS STAC collection](https://stac.dynamical.org/noaa-gfs-forecast/collection.json) · [ICON-EU STAC collection](https://stac.dynamical.org/dwd-icon-eu-forecast-5-day/collection.json) · [ICON grib archive](https://source.coop/dynamical/dwd-icon-grib) · *read: STAC metadata and catalog text*

The same catalog also hosts two more of your three pinned models.
- **GFS (v0.2.7):** 0.25°, init times every 6 h from **2021-05-01**, lead 0–384 h with hourly steps to 120 h; wind at 10, 80 and 100 m; from NOAA's open-data feed on AWS. Latency and reprocessing status are not stated in the metadata.
- **ICON-EU (v0.2.0):** 0.0625° (~7 km), 00/06/12/18 UTC, lead 0–120 h (hourly to 78 h), 10 m wind only; the archive starts **2026-02-10**. A dynamical.org note surfaced by search (I did not open it) says it began archiving DWD's GRIB files in March 2026 because DWD keeps only a short rolling window on its servers, which is consistent with the 2026-02-10 start.
- Also listed: AIFS single and AIFS ensemble (0.25°), and two 46-day IFS ensembles at 1.5°, none of which I examined.
- → GFS is run-addressable for the whole backtest with a 100 m wind field. Check that its archive is first-publication rather than reprocessed, and pin the dataset version.
- → ICON-EU is not retroactively run-addressable anywhere I found; see the table above.
- → GFS runs are every 6 h. Whether the 06 UTC run is available before your cutoff is not something I verified.

### Open-Meteo Ensemble API and Ensemble Mean API
Open-Meteo documentation · [Ensemble API](https://open-meteo.com/en/docs/ensemble-api) · [Ensemble Mean API](https://open-meteo.com/en/docs/ensemble-mean-api) · *read: docs pages*

Members (ECMWF IFS 51, AIFS 51, GEFS 31, ICON-EPS and others) are kept for three days; means and spreads of ensembles are kept longer, but mostly since March 2026.
- → Not usable for a backtest starting September 2024. Usable going forward: self-archive spreads from today, as you already considered for MEPS.

### ECMWF open data (real-time IFS and AIFS)
ECMWF · [confluence page](https://confluence.ecmwf.int/display/DAC/ECMWF+open+data:+real-time+forecasts+from+IFS+and+AIFS) · *read: search excerpt only*

Free CC BY 4.0 real-time forecasts, mirrored on AWS, Azure and Google Cloud.
- The portal keeps only the most recent 12 runs, so it is a live feed rather than an archive.
- → Suitable for the live trial and for self-archiving a forward ensemble.

### Reforecasts: an important dataset for improving weather predictions
Hamill, Whitaker, Mullen · Bull. Am. Meteorol. Soc. 87(1), 2006 ·
[10.1175/bams-87-1-33](https://doi.org/10.1175/bams-87-1-33) · *read: metadata only*

Argues for calibrating on a fixed, consistent model version's past forecasts.
- Statistical corrections learned on one model version degrade when the operational model changes.
- → Track NWP model-version changes inside the two-year window as a possible hidden non-stationarity.

### AROME-MetCoOp: A Nordic Convective-Scale Operational Weather Prediction Model · HarmonEPS—The HARMONIE Ensemble Prediction System
Müller et al. · Weather Forecast. 32(2), 2017 · [10.1175/waf-d-16-0099.1](https://doi.org/10.1175/waf-d-16-0099.1) ·
Frogner et al. · Weather Forecast. 34(6), 2019 · [10.1175/waf-d-19-0030.1](https://doi.org/10.1175/waf-d-19-0030.1) · *read: metadata only*

Descriptions of the 2.5 km Nordic model and its ensemble system.
- → Read for the ensemble's perturbation design and cycle structure. The archive product is named `lagged_6_h`, which suggests members from earlier cycles are combined; check per-member initialisation times against your information-age test.

### Seamless short- to mid-term probabilistic wind power forecasting
Dantas, Browell · arXiv 2025 · [10.48550/arXiv.2502.11960](https://doi.org/10.48550/arXiv.2502.11960) · *read: full text (introduction, method, results and conclusion skimmed)*
PDF: `research/data/papers/dantas2025_seamless-probabilistic-wind.pdf`

One model for 6–162 h ahead on 73 GB wind farms (2019–2023, ECMWF HRES and ENS, BMRA production data), separating weather-forecast uncertainty from weather-to-power uncertainty.
- Stage one is a quantile gradient-boosted weather-to-power model; each ensemble member is dressed with a kernel whose spread coefficients depend on lead time, and the kernels are combined by a beta-transformed linear opinion pool, with all coefficients fitted per lead time by minimum CRPS.
- Distribution tails use a peaks-over-threshold model (generalised Pareto), because non-parametric quantile models struggle in the tails where data are sparse.
- Weather-to-power uncertainty dominates at short lead times; weather-forecast uncertainty dominates beyond about two to three days, later for onshore than offshore farms.
- Ensemble information matters most in high-uncertainty situations such as frontal passages, where methods based on a deterministic forecast fail to capture the extra spread. The deterministic HRES-based quantile model beat the ENS-based one at short horizons, which the authors attribute to HRES's higher temporal resolution and extra variables and levels (their ENS came from TIGGE).
- The data and scripts are on Zenodo (over 200 GB).
- → At your 14–38 h leads the ensemble should add little on average, so judge spread features on the worst days, not on the overall score.
- → Per-lead-hour recalibration coefficients are a direct tool for the lead-hour-34 step, and GPD tails and a beta-transformed pool (Ranjan & Gneiting 2010 and Gneiting & Ranjan 2013, §3) are concrete tools for the under-coverage.
- GB farms with ECMWF inputs; onshore results may differ in the Nordics.

### Determining the bounds of skilful forecast range for probabilistic prediction of system-wide wind power generation
Cannon, Brayshaw, Methven, Drew · Meteorol. Z. 26(3), 2017 · online 2016 ·
[10.1127/metz/2016/0751](https://doi.org/10.1127/metz/2016/0751) · *read: full text*
PDF: `research/data/papers/cannon2017_skilful-range-system-wind.pdf`

Splits the error of global-ensemble wind power forecasts into a resolved part (the ensemble against its own analysis, growing with lead time) and an unresolved part (analysis-derived power against measured power, constant with lead time). Test case: Great Britain's total wind output, TIGGE forecasts from ECMWF, the Met Office and NCEP, four years of twice-daily runs, winds interpolated to farm sites and hub height and turned into power with one generic curve (correlation with measured GB output 0.96 in 2012).
- The lead time beyond which the resolved part exceeds the unresolved one is 2.4 days (ECMWF), 1.9 (Met Office) and 1.4 (NCEP). Skill against climatology ends at 8, 7 and 6 days; for the probability of an extreme ramp, at 5.5, 5 and 4.5.
- The ensemble-mean error was about 6% of GB capacity at short lead times, about 9% after three days and 12% after five.
- The unresolved part contains unresolved local winds, the farms' response to wind, and system operation: curtailment instructions, unreported maintenance and metering errors.
- Their power conversion is cruder than operational ones, so the unresolved part is probably overstated, and the authors say the resolved part could dominate below even 1.4–2.4 days in practice. Better downscaling and microscale modelling have diminishing returns beyond about two days.
- → Your 14–38 h leads sit below the crossover for all three systems, so on average power conversion and non-weather effects drive the error, in line with Browell (§5) and Dantas & Browell above. The curtailment, unreported maintenance and metering effects it names are the same kind of cause as P3 and the high-wind misses, so fixes on the data side have more headroom than adding NWP members.
- GB-wide aggregate (much more diversified than SE3), 2009–2012 data, 0.5° TIGGE grids, 10 m wind.

### Probabilistic wind power forecasting with tree-based machine learning and weather ensembles
Bruninx, van Binsbergen, Verstraeten, Nowé, Helsen · arXiv 2026 (v2, rev. July) ·
[10.48550/arXiv.2602.13010](https://doi.org/10.48550/arXiv.2602.13010) · *read: full text (data, calibration and conclusion sections)*
PDF: `research/data/papers/bruninx2026_tree-based-weather-ensembles.pdf`

Four years of Belgian offshore wind farms (ENTSO-E grid-connection data); compares conformalized quantile regression (XGBoost quantiles plus a conformal margin from a hold-out set), natural gradient boosting (Gaussian) and a conditional diffusion model (Treeffuser, LightGBM-based) against a power curve, an analytical wake model and a Gaussian process.
- Five NWP models via a commercial provider (ICON-EU, ICON-D2, ECMWF HRES, ARPEGE-EU, Met Office Global), taking for each day the latest forecast published before day-ahead gate closure. Using the provider forecasts together improved MAE by 17% over the average single provider and up to 23% over the worst; Diebold–Mariano tests are reported.
- Tree models cut point error by up to 33% versus the power curve and 53% versus the wake model.
- Reliability is reported per operating region of the power curve. The Gaussian methods are worst calibrated at low and high output, where the distribution is asymmetric; the distribution-free methods (CQR, diffusion) are better. The authors also note that storm conditions cause the largest day-ahead errors.
- Diffusion was best overall but far slower; CQR was nearly as good at a fraction of the computation.
- Engineering baselines were rescaled by the ratio of maximum observed power to rated power, and curtailments were filtered from the training data.
- → Per-region reliability curves are a ready-made diagnostic for your high-wind under-coverage (bin by predicted output, cf. Lerch et al. 2017).
- → Independent support for keeping several NWP models, and for CQR as the low-cost calibration option; the max/rated rescaling is another empirical capacity correction.
- Offshore, one zone; the multi-provider gain is over single providers, not over an ensemble.

### Machine learning forecasts of Scandinavian numerical weather prediction wind model residuals with control theory for wind energy
Chen, Zhang, Birkelund · Energy Rep. 8, 2022 · [10.1016/j.egyr.2022.08.105](https://doi.org/10.1016/j.egyr.2022.08.105) · *read: metadata only*

Forecasts the errors (residuals) of a Scandinavian NWP wind model with ML; a companion statistical analysis of the residuals is at [10.1016/j.egyr.2022.07.080](https://doi.org/10.1016/j.egyr.2022.07.080).
- → Candidate for a residual-correction step on the NWP wind itself, before the power curve. I did not read it, so which NWP model, sites and horizons are unknown.

---

## 5. Nordic and Swedish (SE3) studies

### Probabilistic forecasting of regional wind power generation for the EEM20 competition: a physics-oriented machine learning approach
Bellinguer, Mahler, Camal, Kariniotakis · 2020 17th Int. Conf. European Energy Market (EEM) ·
[10.1109/eem49802.2020.9221960](https://doi.org/10.1109/eem49802.2020.9221960) · *read: full text (6 pages)*
PDF: `research/data/papers/bellinguer2020_eem20-physics-oriented-ml.pdf`

The winning entry of the EEM20 competition: day-ahead quantile forecasts (10–90%) of aggregate wind power for the four Swedish zones, beating second and third place by 6.7% and 14.7% in pinball loss.
- Data: hourly regional production, a turbine list (coordinates, rated power, hub height, commissioning dates) and a 10-member 10 km MET Norway ensemble with 10 m wind, gust, temperature, pressure, humidity and cloud.
- **Target:** load factor with a deliberately robust denominator, the mean of registered installed capacity and the running maximum of observed regional output up to that time, because the turbine list was unreliable. They found production above installed capacity in SE1 (November 2000) and a 4% gap between the dataset's capacity (8,640 MW) and the wind association's (8,984 MW).
- One quantile regression forest per zone; features are an analog production level (average load factor of the 200 most similar past weather patterns, found by PCA on hub-height wind), wind-physics variables (power-law shear to 100 m, air density, wind power density, a generic power curve applied at 20–25 capacity-weighted farm clusters), values at t−1 and t+1, and hour of day and day of week as proxies for maintenance and curtailment.
- Used only the ensemble mean, citing an earlier finding that using all members individually performs similarly.
- The northern zone had the highest normalised error, attributed by earlier work to low capacity, complex terrain and icing.
- → The running-maximum denominator is close to the diagnostic your README uses to detect capacity drift. It shows a way to keep using the data despite an unreliable register, while hiding any real drift in the ceiling.
- → Time-shifted features and time-of-day proxies are cheap additions if you lack them.
- Competition data with anonymised dates (2000–2001) and a 2020-era fleet.

### Quantile combination for the EEM20 wind power forecasting competition
Browell, Gilbert, Tawn, May · 2020 17th Int. Conf. European Energy Market (EEM) ·
[10.1109/eem49802.2020.9221942](https://doi.org/10.1109/eem49802.2020.9221942) · *read: full text (6 pages)*
PDF: `research/data/papers/browell2020_eem20-quantile-combination.pdf`

Second-place entry (the authors' team was Team 12): quantile forecasts (0.1–0.9) of wind power for SE1–SE4 from a gradient-boosted tree model and a quantile GAM, combined with quantile-specific weights. The NWP was a 10 m ensemble issued at 06 UTC the day before; each of six two-month tasks appended new data to the training set; scores are pinball loss.
- The GAM was better toward the tails and the trees in the middle, so a per-quantile weight, chosen by cross-validation, beat both components in all four zones.
- Feature engineering used ensemble means (wind speed, gust, direction, temperature, power from shear plus a smoothed generic curve), ±2 h rolling means and lead/lag values, seasonal terms, and the neighbouring zones' median forecasts.
- **The ensemble mean was sufficient:** they could not extract benefit from ensemble range, minimum or maximum. They note that only 10 m wind was available and cite Cannon et al. (2017, §4) for weather-to-power conversion being a much larger source of day-ahead uncertainty than the NWP.
- **Capacity:** the supplied list was imperfect because farms did not come online at their full listed capacity, so they corrected it manually using lags between installation dates and increases in the rolling maximum of recorded power. In SE1 the corrections lowered capacity by about 5% on average and reduced pinball loss by 10% against the raw capacity.
- Final scores (average pinball loss, units as in the paper's Table II): winner 44.9, this entry 47.9, third 51.5, and a combination of the winner and this entry 44.4.
- The authors note that pinball loss lets a forecaster trade reliability for sharpness, and that no competition design yet prevents it.
- → Capacity error moved the score more than any modelling choice reported, and the correction method is the rolling-maximum comparison you already use.
- → Tail-specific model choice and per-quantile combination are concrete P1 experiments.
- Competition data: open access, 28 GB, CC BY 4.0, dates shifted to 2000–2001 ([10.15129/02db89e9-64d1-4ded-9324-6d952ce35099](https://doi.org/10.15129/02db89e9-64d1-4ded-9324-6d952ce35099)); the R package ProbCast is on [Zenodo](https://doi.org/10.5281/zenodo.3843333).

### Day-ahead wind power predictions at regional scales: post-processing operational weather forecasts with a hybrid neural network
Basu, Watson, Lacoa Arends, Cheneka · 2020 17th Int. Conf. European Energy Market (EEM) ·
[10.1109/eem49802.2020.9221979](https://doi.org/10.1109/eem49802.2020.9221979) · *read: full text (6 pages)*
PDF: `research/data/papers/basu2020_eem20-hybrid-nn.pdf`

Third-place EEM20 entry (same four Swedish zones, HARMONIE 10 km, 10-member ensemble, 4,004-turbine list, scored by pinball loss): a network with a convolutional branch on the 10 m wind field and a small perceptron branch on a physics-based first-guess power.
- The first guess extrapolates 10 m wind to hub height with a fixed shear exponent of 0.3, applies a temperature and elevation density correction, and runs each turbine through one generic IEC class-1 power curve; the zone sums are the perceptron's four inputs, with hour of day.
- Only wind and temperature were used; gusts, cloud cover and humidity were left out on domain-knowledge grounds. Only ensemble member 1 (and in some runs the median field) fed the convolutional branch.
- Quantiles come from 100 separately trained networks with randomised data order (6.14 million parameters each, mean-absolute-error loss).
- Adding the ensemble-median channel made results worse (for example 41.96 against 40.77 for the July–August 2001 task). Longer training helped clearly: training on 2000 only gave 45.84 for the same task and 77.37 against 63.43 for November–December 2001, a period in which capacity was still growing.
- The supplied turbine list had spurious entries (1 m hub heights); the organisers' own note gives 4,004 turbines and 8,640 MW against 4,099 and 8,984 MW reported by the Swedish Wind Power Association, about 4% lower. Three days of NWP were missing.
- The authors were coupling the model with ERA5 to separate input error from model error, the idea behind your ERA5 ceiling.
- → A physics-based first-guess power as an input feature is the same pattern as a turbine-level fleet model feeding a learned correction.
- → The training-window result (more, later data clearly better while the fleet grows) bears on how far back the SE3 training set should reach.
- Conference paper with no calibration analysis; the competition data cannot be joined to your archives (dates shifted to 2000–2001).

### A novel day-ahead regional and probabilistic wind power forecasting framework using deep CNNs and conformalized regression forests
Jonkers, Nieves Avendano, Van Wallendael, Van Hoecke · Applied Energy 361, 2024 ·
[10.1016/j.apenergy.2024.122900](https://doi.org/10.1016/j.apenergy.2024.122900) · *read: full text (introduction, data, results and conclusion; methodology sections on CQR/SCPS/SCDRF skimmed)*
PDF: `research/data/papers/jonkers2024_eem20-cnn-conformal-forests.pdf`

Trains on the EEM20 dataset (same four Swedish zones, turbine list and 10-member MET Norway ensemble as Bellinguer, Browell and Basu, above) and directly benchmarks against those three competition entries plus new deep and tree-based baselines.
- Introduces a "turbine map": a 2D grid encoding turbine location and capacity, stacked as an extra channel alongside the gridded NWP variables, so a single dense CNN (DenseNet) can be trained across all four zones and stay context-aware as the turbine mix changes over time — their fix for the same distribution-shift problem Bellinguer's running-maximum denominator and Browell's manual capacity correction address differently.
- For point forecasts, DenseNet beat ResNet and MaxViT on MAE/NMAE in every task.
- For quantiles, compares LQR, QXGB (boosted trees) and QRF, each with and without Conformalized Quantile Regression (CQR), plus their own Split Conformal Predictive System (SCPS) and a new method, Split Conformal Distribution Regression Forests (SCDRF, QRF combined with CPS) that outputs a full predictive distribution rather than fixed quantiles.
- A logit-transformed nonconformity score (mapping the [0,1]-bounded load factor through logit before scoring) improved CQR/SCPS efficiency (narrower intervals at equal empirical coverage) over the plain residual score in most cases.
- Uncalibrated quantile models were the worst performers and visibly overconfident (reliability plots below the diagonal), attributed to overfitting from the CNN's/QGBT's flexibility — calibration was necessary regardless of base model.
- Headline numbers: CQR-logit-QRF reached an average pinball loss of 44.10 MW, 6.86% better than the best published EEM20 result (Bellinguer et al., 46.68 MW); DenseNet100-k12-BC with CQR-logit-QRF cut pinball loss 19.45% versus Basu et al.'s CNN. SCDRF gave the best CRPS (0.04299) of all methods tested.
- → A second, independent confirmation (after Lindberg 2023/2024, §3/above) that quantile-forest and boosted-tree outputs need a calibration layer, not just more capacity or features, to stop being overconfident — direct evidence for P1.
- → The turbine-map idea is a concrete way to make one model handle capacity growth/relocation across zones, relevant if SE1-style fleet changes get handled with a shared model rather than per-zone retraining.
- → Logit-transforming a [0,1]-bounded target (load factor) before computing conformal nonconformity scores is a cheap, testable tweak for whatever conformal layer gets built for P1.
- Competition data, anonymised 2000–2001 dates, 2020-era fleet — same caveat as the other EEM20 entries.

**Three further precedents for the turbine-map/spatial-encoding idea**, found in a broader search prompted by the entry above. None are EEM20 or Nordic-specific, and none are cited by Jonkers et al. — kept here rather than in a new section since they only make sense next to that entry.

### Scene learning: Deep convolutional networks for wind power prediction by embedding turbines into grid space
Yu, Liu, Li, Lu, Ma, Yu, Wang, Li · Applied Energy 238, 2019 ·
[10.1016/j.apenergy.2019.01.010](https://doi.org/10.1016/j.apenergy.2019.01.010) · *read: full text (introduction, related work, results and conclusion; the STF-construction method section skimmed)*
PDF: `research/data/papers/yu2019_scene-learning-turbine-grid.pdf`

Maps each turbine's live SCADA state (wind speed, power) onto a 2D grid ("scene") by relative geographic position, forming a multi-channel image sequence over time (a "spatio-temporal feature", STF); a CNN then predicts the future scene directly, so one forward pass forecasts every turbine in the region in parallel. 592 turbines, one Chinese wind-farm cluster.
- Compared against kNN and SVR fed either the flattened scene or each turbine's own history. STF+FC-CNN cut average MSE from 10.05 MW² (best baseline) to 7.78 (24.1% lower, up to 45.55% on individual turbines) and training time from 91,000–207,000 s (SVR) to about 1,000–1,200 s, a >150× speedup.
- Adding per-turbine weather variables as further channels (multi-STF) improved results again, to 7.25–7.35 MW² average.
- → This is the direct, six-years-earlier precedent for "rasterize turbine positions into grid space, run a CNN over it." The structural difference from Jonkers 2024 is that here the grid pixels *are* the turbine measurements (bottom-up, turbine-level nowcasting), where Jonkers' turbine map is a static capacity mask concatenated with a *separate* NWP grid (top-down, zone-level day-ahead). Jonkers' narrower claim — turbine map combined specifically with an NWP grid — may still hold up; the general "embed turbines into grid space" idea does not originate with them.
- Turbine-level SCADA nowcasting on one wind-farm cluster, not a day-ahead NWP-driven regional-zone setup, so the numbers don't transfer, only the architecture pattern.

### Localized convolutional neural networks for geospatial wind forecasting
Uselis, Lukoševičius, Stasytis · Energies 13(13), 3440, 2020 ·
[10.3390/en13133440](https://doi.org/10.3390/en13133440) · *read: full text (introduction/motivation, architecture table, WIND and METAR results; synthetic bouncing-ball section and mutual-information ordering appendix skimmed)*
PDF: `research/data/papers/uselis2020_localized-cnn-geospatial-wind.pdf`

States the general problem precisely: plain CNNs are translation-invariant by construction, but in geospatial forecasting each grid location has its own intrinsic features (terrain, local climate, in this project's case installed capacity), so a shared filter can't learn location-specific behaviour without help. Formalises and compares several ways to fix this — explicit x/y coordinate channels (CoordConv), learnable per-location latent inputs (LI), and localized/non-shared filter weights per location (LW) — each addable to any conv layer with little extra cost.
- Tested on a synthetic "bouncing ball" benchmark plus three real wind datasets: NREL's WIND Integration National Dataset (10×10 grid, Indiana, 5–60 min horizons), an unordered METAR station network re-embedded onto a grid by mutual information, and a third real dataset.
- On the WIND dataset every localized variant beat its non-localized counterpart at short horizons (5–20 min), where spatial structure matters most; the LI variant had the fewest parameters of any model tested and still beat CoordConv. At longer horizons (30–60 min) a plain LSTM with no spatial component became competitive or best — the spatial-input advantage shrank as lead time grew.
- → Theoretical grounding for *why* a turbine map helps: it's one instance (closer to their "LI" than to CoordConv, since it carries real capacity information rather than just coordinates) of a documented, systematically-tested class of fixes. Also flags a caveat Jonkers doesn't test: their result is on the WIND dataset's much shorter 5–60 min horizons, and this paper's own finding is that spatial encoding's edge fades with lead time — worth checking whether the turbine map's share of Jonkers' pinball-loss gain holds up at 24 h vs. 48 h ahead, day-ahead's full range.
- → The "reorder an unordered set of locations onto a grid by mutual information" trick (§6.3) is reusable if a turbine or plant list ever needs a grid layout without trustworthy coordinates.
- 5–60 minute horizons, not day-ahead; one US grid plus one station network, no wind-power capacity or fleet-growth angle.

### WindDragon: automated deep learning for regional wind power forecasting
Keisler, Le Naour · Environmental Data Science, 2025 (workshop version: ICLR 2024 "Tackling Climate Change with ML") ·
[10.1017/eds.2025.10](https://doi.org/10.1017/eds.2025.10) · *read: full text, workshop version* (arXiv 2402.14385, Feb 2024)
PDF: `research/data/papers/keisler2024_winddragon-automl-wind.pdf`

Short-term (1–6 h) French national wind power forecasting from ECMWF HRES wind-speed maps (100 m, 9 km, hourly, 4 runs/day), submitted the same month as Jonkers et al. National forecast is built bottom-up from France's 12 administrative regions, which the authors found beats forecasting the national total directly.
- To handle turbines being unevenly scattered within an administrative region, each region's NWP map is cropped to the **convex hull of the area around that region's wind farms** (their Fig. 3) instead of the raw administrative boundary, producing a seamless region-specific map — the same instinct as a turbine map (shape the spatial input to where the turbines actually are), though without a capacity-weighted channel; installed capacity is instead used only to scale the power target, updated quarterly.
- WindDragon (DRAGON, an evolutionary AutoML search over architecture + hyperparameters, one search shared across all 12 regions) is benchmarked against CNN, ViT and XGBoost-on-mean-wind-speed baselines, plus persistence.
- National results (aggregated over the 12 regions): full spatial NWP maps with any DL regressor clearly beat collapsing the map to its mean (XGBoost-on-mean 416.7 MW / 9.2% NMAE vs. CNN 369.0 MW / 8.1%, ViT 385.7 MW / 8.5%); WindDragon reached 346.7 MW / 7.7% NMAE, 6% better than the CNN and about 17% better than XGBoost-on-mean — roughly a French town of 32,000 people's annual consumption.
- → Independent, near-simultaneous confirmation (different country, grid operator and horizon) that a full gridded NWP map beats a collapsed mean for regional wind power, and that shaping the map to true turbine geography (their convex hull; Jonkers' capacity mask) is worth doing over an arbitrary administrative or bidding-zone boundary.
- 1–6 h horizon only, not day-ahead; the evolutionary architecture search is a real operational cost the paper doesn't compare against a fixed architecture at equal training budget.

### Day-ahead probabilistic forecasting at a co-located wind and solar power park in Sweden: Trading and forecast verification
Lindberg, Lingfors, Arnqvist, van der Meer, Munkhammar · Adv. Appl. Energy 9, 2023 ·
[10.1016/j.adapen.2022.100120](https://doi.org/10.1016/j.adapen.2022.100120) · *read: full text*
PDF: `research/data/papers/lindberg2023_se3-qrf-verification.pdf`

Three 2 MW turbines plus 2.7 MWp of PV on the Swedish west coast (July 2016 – May 2020, 15-minute data summed to hourly); MEPS control member, 00 UTC cycle, lead hours 24–48, 80 m wind derived from model levels; quantile regression forest then quantile regression; the effect of the wind-to-PV ratio on accuracy and trading value.
- The forest alone was under-dispersive ("predictive distributions too narrow on average") even after extending the tuning and training data. A linear quantile regression on the forest's quantiles, fitted on a separate year, improved calibration but not perfectly.
- Split: 8,760 h to train the forest, a further 8,760 h to fit the recalibration, a final 8,760 h to test, rotated three ways ("shuffles" are block rotations, not random days).
- One forest per lead hour; n_estimators 400–2000, min_samples_leaf 10–20 and max_features 2 chosen by 10-fold CV minimising CRPS.
- Cleaning: output capped at nominal, days dropped when output was zero while NWP wind exceeded 7 m/s (downtime), values normalised by nominal capacity.
- The best mix was 50–60% wind: the aggregated series is smoother, which improved calibration and sharpness. Wind-only CRPS rose with daily variability, except on days ramping from low output to rated power, where output above rated speed is flat and easy to forecast.
- → "Second-stage quantile regression on first-stage quantiles, on a separate calibration block" is the cleanest published precedent for a problem-1 fix and uses the same MEPS product family you are integrating.
- → Their absolute errors are not comparable to yours: a 6 MW park is far less smooth than a 4.6 GW zone.
- → The downtime-day rule (zero output with high NWP wind) is a cheap outage/curtailment filter, cf. IEA 13.2.1.

### Forecasting onshore wind generation in European bidding zones using deep learning
Kean, O'Sullivan · npj Clean Energy 2, 19 (2026) ·
[10.1038/s44406-026-00036-6](https://doi.org/10.1038/s44406-026-00036-6) · *read: full text*
PDF: `research/data/papers/kean2026_bidding-zones-deep-learning.pdf`

One recurrent network trained on 36 bidding zones (ENTSO-E onshore wind, 2020–2024, test year 2024); reports 25.65% lower RMSE and 26.56% lower MAE than the ENTSO-E day-ahead forecasts over 30 zones.
- **The weather inputs are not forecasts.** The paper says historical weather from Open-Meteo is "used as a proxy for forecasts", with historical values shifted to simulate forecast lead, and its reference points to the Historical Weather API. The model therefore sees near-observed weather, while the ENTSO-E forecasts it beats were made from real NWP.
- The ENTSO-E forecasts are aggregated from asset owners and must be submitted by 18:00 Brussels time; the issue time is not recorded in the data.
- The model was not better than ENTSO-E in GR, NO1, NO3 and ES, and 5 of the 7 lowest-ranked zones were Norwegian or Swedish. Gains from pooling zones are attributed to data volume: per-zone networks did worse.
- Capacity: official capacity was missing for Sweden and Italy, so it was estimated from the 95th-percentile load factor of zones with known capacity. Generation is normalised to load factor; 3,708 hours with load factor above 1 were interpolated, and stretches of 6 hours or more with zero or static output were dropped.
- The authors note that new farms at locations with no weather reading can distort load-factor normalisation in zones with fast capacity growth.
- → Do not cite the TSO comparison as evidence. Zone pooling and the load-factor cleaning rules are the transferable parts.
- → Swedish capacity had to be estimated even here, a reminder that public capacity for SE zones is patchy (problem 3).

---

## 6. Capacity denominator, data quality and reanalysis (P3)

No paper reports the specific drift in the ratio of peak output to registered capacity. The closest material explains why fleet maxima sit below capacity (Olauson 2018) and shows how the EEM20 competitors handled an unreliable Swedish capacity register (§5: Bellinguer 2020; Browell 2020).

### Modelling the Swedish wind power production using MERRA reanalysis data
Olauson, Bergkvist · Renewable Energy 76, 2015 ·
[10.1016/j.renene.2014.11.085](https://doi.org/10.1016/j.renene.2014.11.085) · *read: abstract + method sections skimmed*
PDF: `research/data/papers/olauson2015_swedish-wind-merra.pdf`

Hourly aggregated Swedish wind power from MERRA reanalysis plus turbine-registry data (coordinates, rated power, hub height), 2007–2012 while capacity grew from about 600 to over 3,500 MW, checked against the TSO's series.
- Hourly energy errors of 2.9% MAE and 3.8% RMS nationally, 3.7% and 4.2% MAE in the two southern price areas, and 6.5% in the north (attributed to low capacity, complex terrain and icing losses).
- Two factors explained the good fit: a globally optimised power-curve smoothing parameter (standing in for wake losses and multi-turbine smoothing) and correction of seasonal and diurnal bias.
- For SE1 from 2010, hourly production was often above installed capacity; the authors contacted the TSO and the Energy Agency but did not resolve it, so no SE1 model was calibrated.
- → A registry-versus-production inconsistency in Swedish data is documented from 2014, of the opposite sign to your drift but the same kind.
- → A seasonal-and-hourly bias correction is a template for the ERA5 ceiling work.

### ERA5: The new champion of wind power modelling?
Olauson · Renewable Energy 126, 2018 ·
[10.1016/j.renene.2018.03.056](https://doi.org/10.1016/j.renene.2018.03.056) · *read: abstract + method sections (accepted manuscript)*
PDF: `research/data/papers/olauson2018_era5-wind-power.pdf`

Compares ERA5 and MERRA-2 for modelling aggregate generation in five countries and generation of 1,051 individual Swedish turbines; ERA5 performs better in all analysed aspects.
- **Why maxima sit below capacity:** wake losses, mild icing and degraded blades shift the power curve but do not lower the maximum ("internal" losses). Downtime and some electrical losses can lower the maximum, and reanalyses understate wind-speed diversity, since all farms in a country are never above rated speed together, so generation in Germany, France and Sweden "will seldom exceed 0.8 p.u." ("external" losses).
- The model represents these by reducing the energy in the wind by a fixed amount (internal) and multiplying the output by a factor (external), fixing the mean capacity factor and the maximum from measurements; the external factor is set to 1.01 times the measured maximum.
- Turbine downtime is detected where measured output is zero for at least five hours while reanalysis output is high, with rules on duration and level.
- → A ceiling of roughly 0.8 is normal for Sweden. The open question is why it was near 0.9 in 2018, and what changed: downtime, curtailment, or the diversity of where capacity sits.
- → A model that is calibrated to the measured maximum cannot reveal a drifting ceiling; apply the calibration in a fixed window and evaluate outside it.
- → Matches the turbine-level fleet model in your ERA5 ceiling commit (`5dd7e46`).

### Using bias-corrected reanalysis to simulate current and future wind power output
Staffell, Pfenninger · Energy 114, 2016 ·
[10.1016/j.energy.2016.08.068](https://doi.org/10.1016/j.energy.2016.08.068) · *read: abstract + data and capacity sections skimmed*
PDF: `research/data/papers/staffell2016_bias-corrected-reanalysis.pdf`

Validates MERRA and MERRA-2 for 23 European countries: large spatial bias (over 50% too high in the north-west, about 30% too low in the Mediterranean), corrected by national factors that bring hourly national output to R² above 0.95.
- The correction factors are relatively stable over time but vary by about ±32% across space.
- Capacity handling: annual output is combined with start-of-year capacity snapshots using the geometric mean of the start of the year and the start of the next, assuming constant growth; only farms existing at each time are simulated, not a static fleet snapshot.
- ENTSO-E outputs were reduced by 5% to allow for transmission and distribution losses so that they agreed with other sources, and the ENTSO-E series differed most from the others in some periods.
- Sweden and Spain could not be included in the fleet-evolution analysis for lack of farm construction dates.
- → The 5% ENTSO-E adjustment is a reminder to check which basis (gross or net at grid) the SE series is on relative to capacity.
- → Fleet-at-time-t simulation is the right design for the turbine-level model.

### The ERA5 global reanalysis
Hersbach et al. · Q. J. R. Meteorol. Soc. 146, 2020 ·
[10.1002/qj.3803](https://doi.org/10.1002/qj.3803) · *read: abstract (via Crossref)*

31 km hourly reanalysis with an ensemble-based uncertainty estimate (3-hourly, half resolution).
- → That uncertainty estimate describes analysis error, not forecast spread, so it will not fix P1.

### The ENTSO-E Transparency Platform — a review of Europe's most ambitious electricity data platform
Hirth, Mühlenpfordt, Bulkeley · Appl. Energy 225, 2018 ·
[10.1016/j.apenergy.2018.04.048](https://doi.org/10.1016/j.apenergy.2018.04.048) · *read: search excerpt*

Compares platform data with Eurostat and other sources for 2015–2016; finds shortcomings tied to weak data-quality governance.
- → Cross-check Swedish generation and capacity against a second source (national statistics or Svenska kraftnät data) before trusting either as the denominator.

### Two preregistered datasets on production-type labelling in the ENTSO-E Transparency Platform: multi-fuel reporting, register vintages, persistent misclassification, and cross-product consistency
Nicolaysen · arXiv 2609.16152, submitted 2026-09-14 ·
[10.48550/arXiv.2609.16152](https://doi.org/10.48550/arXiv.2609.16152) · *read: full text (11 pages); unreviewed preprint*
PDF: `research/data/papers/nicolaysen2026_entsoe-production-type-labelling.pdf`

Two preregistered checks of how ENTSO-E labels production types (simultaneous multi-fuel reporting, type changes between register vintages, persistent misclassification, per-unit against aggregated consistency), mostly on thermal plants.
- Every ENTSO-E series in the material has curve type `A03`, in which a missing position means the previous value holds. Summing only the listed points under-reported three Finnish units in 2021 by 4.9%, 7.2% and 22.6%. Periods with position gaps were 3,265 of 12,417 (FI 2021), 14,278 of 23,403 (GB 2021) and 171 of 240 (NL 2023). The author's own early parser made this error and three published versions carried it before two independent implementations disagreed.
- No per-unit generation series (A73) is published for SE3 (probed for 2019, 2021 and 2023; the API returns acknowledgement code 999), nor for DE-LU. A73 covers only units of 100 MW or more, so A73 below A75 is normal.
- Control checks: wind aggregates came out at 0.94–0.98× of national sources in France and Finland, nuclear at 0.99–1.00×. ENTSO-E reports net generation and Eurostat gross, so establish which one a national figure is before comparing.
- Converted plants keep stale fuel labels in the register; this concerns thermal plants, not wind capacity.
- → entsoe-py 0.7.11 (pinned in this repo) reindexes each Period and forward-fills `A03` gaps in its generic time-series parser, and `grid_signals` ingestion goes through `EntsoePandasClient.query_generation`, so this failure mode is probably already handled. I have not tested it on an SE3 response, and it is no evidence about the 0.91 → 0.79 ceiling drift.
- → A wind aggregate can sit a few percent below national sources in some zones, but a fixed ratio would not explain a drift.
- Single author, days old, and about thermal labelling rather than wind.

### Modelling regional solar photovoltaic capacity in Europe: A data-driven approach for disaggregation, benchmarking, and forecasting
Alghanem, Buckley · Energy Rep. 14, 2025 · [10.1016/j.egyr.2025.07.010](https://doi.org/10.1016/j.egyr.2025.07.010) · *read: metadata only*

Data-driven disaggregation and forecasting of PV capacity by region.
- → Solar analogue of P3: the capacity denominator for PV is itself modelled, so start solar with a plan for it.

---

## 7. Regional aggregation, high wind and shutdowns

### Probabilistic forecasting of temporal trajectories of regional power production — Part 1: Wind
Thorarinsdottir, Løland, Lenkoski · arXiv 2019 ·
[10.48550/arXiv.1903.01186](https://doi.org/10.48550/arXiv.1903.01186) · *read: full text (12 pages), method and data sections*
PDF: `research/data/papers/thorarinsdottir2019_regional-wind-trajectories.pdf`

Bayesian model for hourly German aggregate wind power: cubic transform of power, multivariate Gaussian errors with a correlation structure across lead times, NWP covariates; German production from EEX, trained on 2011 and tested on 2012.
- NWP is the 50-member ECMWF ensemble at 0.25° (about 32 km over Germany), 00 UTC, 3–6 hourly, lead up to 72 h for 100 m wind. Members are treated as exchangeable and reduced to their average.
- Preprocessing: spline interpolation of 3-hourly values to hourly (constrained to be non-negative), and a spatial average over the northern half of the country only (371 grid cells), where the wind power is concentrated, which gave a stronger link to production.
- Calibrated and skilful marginal forecasts (PIT histograms show minor deviations); several formulations of the correlation across lead times are compared.
- Notes the need for an up-to-date account of installed capacity.
- → Your worst day was wrong by about 520 MW for 24 hours straight: errors are strongly autocorrelated within a day, so per-hour bands understate whole-day risk.
- → The northern-half averaging is a precedent for weighting NWP points by where capacity actually is, as your eight capacity-weighted points do.

### On autoregressive deep learning models for day-ahead wind power forecasts with irregular shutdowns due to redispatching
Meisenbacher et al. · at – Automatisierungstechnik 73, 2025 ·
[10.1515/auto-2024-0171](https://doi.org/10.1515/auto-2024-0171) · *read: abstract + introduction (arXiv version)*
PDF: `research/data/papers/meisenbacher2024_redispatch-shutdowns.pdf`

Compares three autoregressive deep models with power-curve models at turbine level on German onshore data with regular and irregular (redispatch) shutdowns.
- Autoregressive models are vulnerable because they learn and can reproduce shutdown behaviour; power-curve methods gave lower errors with less data cleaning and lower cost.
- Redispatch interventions are irregular and not forecast, which corrupts any feature built on recent generation.
- → Supports your physics-first design and caution around the lagged-generation features (generation two or more days ago).
- → Swedish congestion-driven down-regulation would behave the same way. Turbine-level German data, so transfer to a zone aggregate is indirect; I found no citable source for its volume in SE3.

### An improved spatial upscaling method for producing day-ahead power forecasts for wind farm clusters
Yang et al. · IET Gener. Transm. Distrib. 16, 2022 ·
[10.1049/gtd2.12569](https://doi.org/10.1049/gtd2.12569) · *read: search excerpt*

Statistical upscaling from reference farms to a cluster.
- → Alternative to the eight-point capacity-weighted power curve.

### Aggregated wind power characteristic curves and artificial intelligence for regional wind power infeed estimation
Li, Janik, Schwarz · Electr. Eng. 106(1), 2023 (online) ·
[10.1007/s00202-023-02005-z](https://doi.org/10.1007/s00202-023-02005-z) · *read: search excerpt*

- One turbine's power curve is not enough for a region; farms differ in cut-in, cut-out and slope, so an aggregated regional curve is needed.
- → Suggests the "nothing learned" baseline could use a fitted regional curve rather than a manufacturer-style one.

### High-wind shutdowns: When strong winds mean zero production
Dexter Energy · vendor blog · [dexterenergy.ai/news/high-wind-shutdowns](https://dexterenergy.ai/news/high-wind-shutdowns/) · *read: full page; marketing, not peer-reviewed*

Explains cut-out (about 25 m/s), staggered shutdowns within a park, and why smoothed NWP fields miss local gusts.
- Claims shutdown hours cause a disproportionate share of balancing cost, but cites no data.
- → Use for hypotheses only. A cheap test: check whether under-coverage concentrates in hours where high-percentile forecast wind speed across the eight points nears cut-out.

---

## 8. Sub-hourly and market resolution (P4)

Little peer-reviewed work on day-ahead, zone-level, 15-minute VRE forecasting turned up; search hits were mostly vendor blogs, which I did not rely on.

### Minute-scale forecasting of wind power — results from the collaborative workshop of IEA Wind Task 32 and 36
Würth et al. · Energies 12(4), 2019 · [10.3390/en12040712](https://doi.org/10.3390/en12040712) · *read: abstract*

Workshop findings on minute-scale forecasts for turbine control, grid balancing and market use.
- Aimed at horizons far shorter than day-ahead.
- → Useful mainly as a vocabulary and metrics reference for intra-hour variability.

### Day-ahead bidding strategies for wind farm operators under a one-price balancing scheme
Bruninx, Verstraeten, Kazempour, Helsen · arXiv 2025 ·
[10.48550/arXiv.2505.05153](https://doi.org/10.48550/arXiv.2505.05153) · *read: abstract*

Under one-price balancing the profit-maximising bid becomes all-or-nothing; a risk-constrained stochastic approach keeps most of the gain over point-forecast bidding.
- Belgian offshore wind, not Nordic.
- → Shows why calibrated tails matter more once the market settles in 15-minute blocks.

---

## 9. Evaluation methodology (EVAL)

### Forecaster's dilemma: extreme events and forecast evaluation
Lerch, Thorarinsdottir, Ravazzolo, Gneiting · Stat. Sci. 32(1), 2017 ·
[10.1214/16-sts588](https://doi.org/10.1214/16-sts588) · *read: metadata only*

Shows that evaluating forecasts only on cases selected by extreme observed outcomes rewards hedging and distorts scores.
- → Check how `coverage_by_output.png` bins: by realised output, even a perfectly calibrated forecast shows sub-nominal coverage in the highest bin. Bin by the forecast (or forecast quantile) instead.
- → The same caution applies when reading results off the "worst day in the period".

### Comparing density forecasts using threshold- and quantile-weighted scoring rules
Gneiting, Ranjan · J. Bus. Econ. Stat. 29(3), 2011 ·
[10.1198/jbes.2010.08110](https://doi.org/10.1198/jbes.2010.08110) · *read: metadata only*

Proper scores that put more weight on chosen thresholds or tails.
- → A high-output-weighted CRPS would let model selection care about the hours where errors are most expensive without conditioning on outcomes.

### Strictly proper scoring rules, prediction, and estimation
Gneiting, Raftery · J. Am. Stat. Assoc. 102(477), 2007 ·
[10.1198/016214506000001437](https://doi.org/10.1198/016214506000001437) · *read: metadata only*

Theory of proper scores; CRPS and the quantile (pinball) score are proper.
- Justifies CRPS and pinball as leaderboard metrics.

### Probabilistic forecasts, calibration and sharpness
Gneiting, Balabdaoui, Raftery · J. R. Stat. Soc. B 69(2), 2007 ·
[10.1111/j.1467-9868.2007.00587.x](https://doi.org/10.1111/j.1467-9868.2007.00587.x) · *read: metadata only*

Defines probabilistic, marginal and exceedance calibration and the sharpness principle; PIT diagnostics.
- → Interval coverage is one facet; PIT histograms and exceedance calibration would show *where* the bands fail.

### Stable reliability diagrams for probabilistic classifiers
Dimitriadis, Gneiting, Jordan · PNAS 118(8), 2021 ·
[10.1073/pnas.2016191118](https://doi.org/10.1073/pnas.2016191118) · *read: metadata only*

Reliability diagrams via isotonic regression with bootstrap consistency bands, replacing arbitrary binning.
- → Applicable to exceedance events such as "output above the 90% quantile" without bin-choice artefacts.

### Comparing predictive accuracy
Diebold, Mariano · J. Bus. Econ. Stat. 13(3), 1995 ·
[10.1080/07350015.1995.10524599](https://doi.org/10.1080/07350015.1995.10524599) · *read: metadata only*

Test for whether two forecasts differ significantly in accuracy.
- → With 546 daily blocks, test whether 143 MW vs 166 MW (and the CRPS differences) is significant, using day-level blocks because hourly errors are correlated.

### On the use of cross-validation for time series predictor evaluation · Evaluating time series forecasting models: an empirical study on performance estimation methods
Bergmeir, Benítez · Inf. Sci. 191, 2012 · [10.1016/j.ins.2011.12.028](https://doi.org/10.1016/j.ins.2011.12.028) ·
Cerqueira, Torgo, Mozetič · Mach. Learn. 109, 2020 · [10.1007/s10994-020-05910-7](https://doi.org/10.1007/s10994-020-05910-7) · *read: metadata only*

Empirical studies of cross-validation versus out-of-sample schemes for time series.
- → Background for defending the frozen hold-out and the rolling-origin protocol.

### Trading wind generation from short-term probabilistic forecasts of wind power
Pinson, Chevallier, Kariniotakis · IEEE Trans. Power Syst. 22(3), 2007 ·
[10.1109/tpwrs.2007.901117](https://doi.org/10.1109/tpwrs.2007.901117) · *read: metadata only*

Optimal bid from probabilistic forecasts is a specific quantile of the predictive distribution, set by the ratio of up- and down-regulation costs.
- → The quantile that matters for trading is set by price asymmetry, so calibrating that quantile can matter more than the central band.

### The impact of renewable energy forecast errors on imbalance volumes and electricity spot prices
Goodarzi, Perera, Bunn · Energy Policy 134, 2019 ·
[10.1016/j.enpol.2019.06.035](https://doi.org/10.1016/j.enpol.2019.06.035) · *read: metadata only*

Links VRE forecast errors to imbalance volumes and prices.
- → Supports weighting high-output errors more heavily, since they move prices most.

---

## 10. German solar (SOL)

### Probabilistic forecasting of temporal trajectories of regional power production — Part 2: Photovoltaic solar
Thorarinsdottir, Løland, Lenkoski · arXiv 2019 ·
[10.48550/arXiv.1903.01188](https://doi.org/10.48550/arXiv.1903.01188) · *read: full text (11 pages), method and data sections*
PDF: `research/data/papers/thorarinsdottir2019_regional-pv-trajectories.pdf`

Fully probabilistic hourly model for German aggregated PV with the same set-up as Part 1: EEX production data, 50-member ECMWF ensemble reduced to its average, lead up to several days.
- 3-hourly irradiance is interpolated to hourly by a non-negative spline, with a more advanced alternative interpolating the clear-sky index; forecasts are averaged over 724 grid locations across Germany, since spatial averaging improves irradiance skill.
- Calibrated and skilful forecasts for German PV.
- → Ready-made structure for the German solar track, including the interpolation and spatial-averaging choices.
- 2011–2012 data, so far lower PV penetration than today.

### Regional PV power prediction for improved grid integration
Lorenz, Scheidsteger, Hurka, Heinemann, Kurz · Prog. Photovolt. 19(7), 2011 · online 2010 ·
[10.1002/pip.1033](https://doi.org/10.1002/pip.1033) · *read: full text*
PDF: `research/data/papers/lorenz2010_regional-pv-prediction.pdf`

The Oldenburg/Meteocontrol operational system for the German TSO areas 50Hertz and transpower: ECMWF irradiance and temperature, site-specific post-processing, physical PV simulation of a representative set of systems (77 and 306), scaled up to the region. Evaluated 2 July 2009 – 30 April 2010; forecasts were delivered at 07:00 local time from the previous day's 12 UTC run.
- Irradiance is interpolated in the clear-sky index. A bias correction, a polynomial in the predicted clear-sky index and solar zenith angle, removes the raw forecast's overestimate at intermediate cloud; it is trained on a sliding window of the previous 30 days of measurements from more than 200 German weather stations.
- An additional loss factor of 9.5% covers reflection and spectral losses, mismatch, cabling, soiling and inverter efficiency.
- Nominal power is updated monthly and errors are normalised by the time-dependent installed power. A modified upscaling that models the spatial distribution of installed power on a 1° × 1° grid did slightly better.
- RMSE in % of installed power, intra-day / day-ahead: operational 5.1 / 4.9 (50Hertz) and 4.2 / 4.3 (transpower); modified upscaling 4.3 / 4.3 and 3.9 / 4.1; persistence 7.4 / 9.2 and 6.4 / 8.0. Skill against persistence was 30–40% intra-day and 40–50% day-ahead. Mean output was only 9.1–9.5% of nominal power, so the RMSE is about half the mean.
- Snow: in January–February 2010 forecasts overestimated low output because snow covered modules across a large share of the fleet, and in January persistence beat the forecast. Single situations reached errors of up to 25% of nominal power. Zero readings in daylight were removed as outages only in months without snow.
- The "measured" regional power is an upscaling of the same representative systems, so the upscaling error is not in the reported RMSE (the authors say so).
- → A yardstick for German solar at far lower penetration than today. Errors as a share of installed capacity flatter solar because mean output is under 10% of it, so choose the denominator deliberately (see van der Meer below).
- → A clear-sky-index and zenith-angle bias correction is a cheap post-processing step to test, and snow needs a flag in the way high-wind shutdowns do for wind.
- → Monthly nominal-power updates are the solar counterpart of P3.

### Data-driven upscaling methods for regional photovoltaic power estimation and forecast using satellite and numerical weather prediction data
Pierro, De Felice, Maggioni, Moser, Perotto, Spada, Cornaro · Sol. Energy 158, 2017 ·
[10.1016/j.solener.2017.09.068](https://doi.org/10.1016/j.solener.2017.09.068) · *read: full text (abstract, data, results, prediction-interval section, conclusion)*
PDF: `research/data/papers/pierro2017_regional-pv-upscaling.pdf`

Estimation and forecast of the PV output of 1,985 plants in South Tyrol (800 km², about 7% PV penetration) by clustering the fleet and feeding satellite or NWP inputs at the cluster centroids into neural networks. NWP was WRF hindcasts for 2014–2015, initialised at 12 UTC with the 24 h forecast from the following 00 UTC used for day-ahead.
- Day-ahead RMSE was 7% of installed capacity for one day ahead and 7.5% for two, with skill against smart persistence of 39% and 45%. Averaging over clusters cut the day-ahead RMSE by 12% against a single cluster, and the error fell with area size along a fitted exponential.
- Prediction intervals: a neural network predicts the standard deviation of the error from sun geometry and a pseudo clear-sky performance index, and the Gaussian intervals built from it were too wide, since the observed frequency was almost always above the nominal level except at 95%.
- A per-confidence-level correction coefficient, fitted on 2014 and tested on 2015, brought the reliability plot near the diagonal. The normalised error distributions of the two years were very similar, which is why the correction transferred.
- The error spread peaked near noon in variable-irradiance conditions.
- → Contrast with wind: these solar Gaussian intervals over-covered, so the solar fix for P1 may point the opposite way. Test reliability per nominal level instead of assuming the direction.
- Hindcasts rather than archived operational forecasts, one small region, two years; the ensemble-averaging result concerns fleets of clusters and does not transfer directly to Germany.

### A probabilistic approach to the estimation of regional photovoltaic power production
Saint-Drenan, Good, Braun · Sol. Energy 147, 2017 ·
[10.1016/j.solener.2017.03.007](https://doi.org/10.1016/j.solener.2017.03.007) · *read: full text*
PDF: `research/data/papers/saintdrenan2017_probabilistic-regional-pv.pdf`

A physical PV model that needs only plant locations and capacities from the German register: it simulates the most common module orientations and weights them by their probability of occurrence, taken from a database of more than 35,000 plants, so no plant measurements are needed. Checked against the four German TSOs' published 15-minute PV estimates using IFS forecasts.
- **The TSO "actual" is an estimate**, upscaled from a limited set of reference plants, and the authors say so: validation against it is "of limited relevance from a scientific perspective" but matches how TSOs judge forecasts.
- One constant derating factor per control area (about 0.82) was fitted on 2014 and applied to 2015. Winter months were excluded because snow and shading are not modelled, so only April–October was used.
- RMSE in % of installed capacity: 4.16 (TenneT), 4.76 (Amprion), 4.87 (50Hertz) and 6.13 (TransNetBW). The TransNetBW figure is set aside because that area's register was last updated in July 2014, against April–May 2016 for the others, so the plant set did not match.
- Against the TSOs' published day-ahead forecasts, the model was 0.43 (TenneT) and 0.36 (50Hertz) points of RMSE worse. Amprion's forecast was much worse (5.99) and was set aside as under-average. The authors could not tell which forecast products the TSOs publish or whether they are the ones used operationally.
- Maximum output in the TSO estimates was about 0.6–0.75 of installed capacity, against about 0.8 from the model, which the authors attribute to spatial smoothing that the model underestimates.
- → For the German solar track: the target is itself noisy, so an error floor exists that no forecast can beat (its size for control areas is not established; see the 2016 paper above). Register currency (last entry date) varies by control area, which is P3 again for solar.
- → The 15-minute TSO series is the natural P4 target for solar.
- Register data and 2014–2015 fleet, before roughly a doubling of German PV capacity.

### Analysis of the uncertainty in the estimates of regional PV power generation evaluated with the upscaling method
Saint-Drenan, Good, Braun, Freisinger · Sol. Energy 135, 2016 ·
[10.1016/j.solener.2016.05.052](https://doi.org/10.1016/j.solener.2016.05.052) · *read: full text (abstract, data and conclusion; error analysis skimmed)*
PDF: `research/data/papers/saintdrenan2016_upscaling-uncertainty.pdf`

Measures the error of the upscaling method that underlies the TSOs' PV "actuals", using 15-minute measurements from 366 plants (out of 1,122 with 511 MWp) in one distribution-grid area (LEW Verteilnetz), July 2013 – August 2014. Reference plants are drawn from the same set and the rest are treated as unmetered.
- The error falls steeply up to about 20 reference plants and saturates beyond about 70. With more than 70 the RMSE ranges from 0.009 to 0.022 kW/kWp, mostly 0.010–0.015, and it depends on which plants are chosen: 0.010–0.025 kW/kWp even for a large set.
- The average distance between reference and unmetered plants predicts the error better than the number of reference plants. Mismatched plant characteristics (tilt, azimuth) also raise it, which the dataset could not quantify.
- The sample is medium and large plants; rooftop-heavy fleets probably spread more.
- → This does not give the noise floor of a whole control area, which I had hoped it would. It is one small area, and the paper's own aggregation analysis (its section 5) says the error falls as more plants are aggregated; I did not extract by how much.

### Review on probabilistic forecasting of photovoltaic power production and electricity consumption
van der Meer, Widén, Munkhammar · Renew. Sustain. Energy Rev. 81, 2018 ·
[10.1016/j.rser.2017.05.212](https://doi.org/10.1016/j.rser.2017.05.212) · *read: abstract, definitions and benchmark sections, table of day-ahead studies, conclusion (29 pages, not read in full)*
PDF: `research/data/papers/vandermeer2018_pv-probabilistic-review.pdf`

Uppsala review of probabilistic PV and load forecasting, mostly at site and building scale, with a table of studies, metrics and benchmarks.
- No single model suits every case: one that was re-tuned across case studies performed well but did not beat models optimised for each task.
- Probabilistic metrics are applied inconsistently for PV and no probabilistic benchmark is standard. Proposed ones are a persistence ensemble (the last observations at the same time of day, ranked into quantiles) and a probabilistic climatology.
- CRPS is normalised sometimes by nominal capacity and sometimes by the maximum measured output; the authors suggest reporting both, since the first is transparent and the second reflects seasonal variation.
- Night hours and low-sun hours are filtered inconsistently, and the amount of filtering changes the reported accuracy, so they recommend standardising it. Morning and evening forecasts are inherently harder.
- Assuming a fixed error density (Gaussian) has repeatedly given inaccurate results and generalises poorly across sites.
- Standard practice is to model a clear-sky index rather than raw output.
- → Fix the solar evaluation choices up front (denominator, which hours count, benchmark) and apply them to every solution, in the spirit of IEA 12.1.1.
- Literature up to 2017 and mostly not regional German data.

### A review of solar forecasting, its dependence on atmospheric sciences and implications for grid integration: Towards carbon neutrality
Yang et al. · Renew. Sustain. Energy Rev. 161, 2022 · [10.1016/j.rser.2022.112348](https://doi.org/10.1016/j.rser.2022.112348) · *read: metadata only*

A broad review of solar forecasting and its dependence on atmospheric science.
- → Not read. Chase it only if the solar track needs a wider review; van der Meer above covers the probabilistic side.

### Variable renewable energy forecasting in Germany: Reassessing simplicity with Bayesian-optimised multilayer perceptrons
Wanek · Renewable Energy 262, 2026 · [10.1016/j.renene.2026.125409](https://doi.org/10.1016/j.renene.2026.125409) · *read: full text*
PDF: `research/data/papers/wanek2026_de-vre-mlp.pdf`

Bayesian-optimised MLPs for German national wind and solar, trained on ERA5 for 2015–2023 with installed capacity as an input, 2024 held out; real NWP (ICON, IFS, GFS) used at inference for daily runs in January–April 2025; compared with TSO forecasts; Gaussian intervals from a boosted-tree variance model. Capacity comes from the MaStR register, target data from SMARD.
- Trains on reanalysis and applies the model to forecast NWP, so no archived forecast vintages are needed. The cost is a train–serve mismatch the paper does not quantify, and the real-NWP test covers only about 120 winter days.
- Day-ahead nRMSE 3.7% for wind (IFS inputs) and 2.7% for solar (ICON inputs). IFS was best for wind and ICON best for solar across horizons.
- Intervals are normal with σ from a histogram-based gradient-boosted tree fitted to squared error as a function of forecast level and lead time. Its R² is only 0.18 for wind and 0.27 for solar. Reported coverage is 92.0% (wind) and 96.4% (solar) for a nominal 90%, but it is computed on all collected forecasts, including those the variance model was fitted on, so it is not an out-of-sample check.
- Errors are largest at long lead times and in high-wind situations. Wind outliers above the diagonal are attributed to grid-related curtailment (5.7 TWh in 2024); a low solar bias is attributed to annual capacity not covering intra-year growth.
- → Reanalysis-trained physics-plus-ML is a possible route around problem 2 that your ERA5 work could support; test the train–serve mismatch before relying on it.
- → Its nRMSE for Germany is not comparable to your 143 MW MAE (about 3.1% of capacity): RMSE is at least MAE, and a national aggregate is far more diversified than SE3.
- → For the solar track: ICON is a candidate NWP for DE-LU, and capacity needs interpolating within the year (MaStR is a dated register).

---

## 11. PDFs still missing

Everything else in the earlier lists has been obtained and read. Two items remain:

| # | source | where | why | status |
|---|---|---|---|---|
| 1 | Nikodinoska et al. (2022), *Solar and wind power generation forecasts using elastic net in time-varying forecast combinations*, Appl. Energy | [10.1016/j.apenergy.2021.117983](https://doi.org/10.1016/j.apenergy.2021.117983) | German wind and solar combination of several forecasts; cited by Wanek as a benchmark. For the solar track | cannot be sourced at the moment |
| 2 | Statistics on wind down-regulation and curtailment in SE3 (Svenska kraftnät, Energimyndigheten) | not found; Svenska kraftnät's balancing-data site [mimer.svk.se](https://mimer.svk.se/) responds but I did not check it for wind-specific figures | Would test the redispatch and curtailment explanation for problem 3 and high-wind misses | source unknown |

Not a paper, but on the list: the EEM20 competition data and code (28 GB, open access, CC BY 4.0,
[10.15129/02db89e9-64d1-4ded-9324-6d952ce35099](https://doi.org/10.15129/02db89e9-64d1-4ded-9324-6d952ce35099))
if you want an external benchmark for the Swedish-zone method. Its dates are shifted to 2000–2001
and only 10 m wind is provided, so it cannot be joined to your real archives.

## 12. Gaps

- **P3 (capacity drift):** no paper reports the specific symptom. Olauson 2018 explains why ceilings near 0.8 are normal, and the EEM20 papers show empirical fixes for an unreliable register, but none explains a ceiling that moves from 0.91 to 0.79.
- **P4 (15-minute):** thin peer-reviewed coverage; expect to design this from first principles, using IEA 13.2.2's averaging/instantaneous distinction and the metrics vocabulary in §8.
- **German solar capacity and target:** no study found on register vintage, and on the noise in the TSO "actual" only Saint-Drenan 2017 and its 2016 predecessor, which measures one small area (§10).
- **Swedish curtailment and redispatch magnitudes:** no citable source found.
- **Machine-learning weather models** (AIFS, GenCast, Google WeatherNext) appear as ensembles in Open-Meteo's and dynamical.org's listings. The constraint is archive depth, not quality, so I did not review them further.
- **dynamical.org's own processing delay:** the source-file arrival times are measured (§4); the delay before a run appears in the Zarr store is not.
- **Run-addressing for ICON-EU:** no retroactive source found; see §4.

---

## 13. Parked — do not revisit

PDFs in `research/data/papers/` that were read and judged not worth returning to, with the
reason, so we don't spend time on them again.

| file | why parked |
|---|---|
| `foley2012_methods-review.pdf` — Foley et al., *Current methods and advances in forecasting of wind power generation*, Renewable Energy 37, 2012 · [10.1016/j.renene.2011.05.033](https://doi.org/10.1016/j.renene.2011.05.033) | **Superseded.** An 8-page 2012 overview of physical, statistical and hybrid methods. It predates boosted-tree quantile models, conformal calibration and ML post-processing; Sweeney et al. (2020) and the IEA guide cover the same ground more currently. Nothing new found. |
| `zhang2014_probabilistic-wind-review.pdf` — Zhang, Wang, Wang, *Review on probabilistic forecasting of wind power generation*, Renew. Sustain. Energy Rev. 32, 2014 · [10.1016/j.rser.2014.01.033](https://doi.org/10.1016/j.rser.2014.01.033) | **Superseded.** A 16-page taxonomy of probabilistic methods (parametric, non-parametric, scenario) and evaluation criteria, written before the methods this project uses. The taxonomy is covered by Gneiting & Katzfuss (2014) and Sweeney et al. (2020), and the evaluation criteria by IEA chapter 14. |
| `bremnes2004_local-quantile-regression.pdf` — Bremnes, *Probabilistic wind power forecasts using local quantile regression*, Wind Energy 7, 2004 · [10.1002/we.107](https://doi.org/10.1002/we.107) | **Superseded.** The original local quantile regression on one Norwegian farm. Boosted-tree quantile models (Landry) and the quantile-regression recalibration recipe (Lindberg) replace it; its one idea worth keeping, that quantile forecasts suit economic decisions, appears in Pinson et al. (2007) in §9. |
| `pinson2012_logit-normal-vshort-term.pdf` — Pinson, *Very-short-term probabilistic forecasting of wind power with generalized logit-normal distributions*, J. R. Stat. Soc. C 61, 2012 · [10.1111/j.1467-9876.2011.01026.x](https://doi.org/10.1111/j.1467-9876.2011.01026.x) | **Not relevant to the horizon.** Ten-minute-ahead forecasts with recursively updated parameters at one wind farm; neither the horizon nor the estimation scheme transfers to NWP-driven day-ahead. The only transferable point, keeping bands inside [0, 1] of capacity, can be tested by clipping. |
| `yang2018_analog-storm-wind-dual-nwp.pdf` — Yang, Astitha, Delle Monache, Alessandrini, *An analog technique to improve storm wind speed prediction using a dual NWP model approach*, Mon. Weather Rev. 146, 2018 · [10.1175/mwr-d-17-0198.1](https://doi.org/10.1175/mwr-d-17-0198.1) | **Not relevant.** Analog ensembles with bias correction for 146 storms at US surface stations, built on two regional research models (WRF and RAMS–ICLAMS) that are not among your inputs; wind speed at stations, not power. The analog-ensemble concept and its tail-bias caveat are covered by Alessandrini et al. (2019) and Sweeney et al. (2020). |
| `molinder2021_icing-losses-qrf.pdf` — Molinder et al., *Probabilistic forecasting of wind turbine icing related production losses using quantile regression forests*, Energies 14, 2021 · [10.3390/en14010158](https://doi.org/10.3390/en14010158) | **Conditionally relevant.** Forest-based forecasts of icing-related losses at four Swedish parks over two winters, with a physical icing model as an input; pooling stations helped. Only useful if icing is confirmed as a driver. **Revisit if** temperature and humidity on the highest-error days (for example 13 February 2026) point to icing. The pooling lesson is already covered by Kean & O'Sullivan. |
| `karlsson2026_cold-climate-wind.pdf` — Karlsson et al., *Cold Climate Wind: Challenges, Technological Solutions and Policy*, WIREs Energy Environ. 15, 2026 · [10.1002/wene.70025](https://doi.org/10.1002/wene.70025) | **Not relevant unless icing is confirmed.** A general review of cold-climate wind (loss ranges, mitigation, policy) with no zone-level forecasting content. It reports icing losses ranging from near zero to over 20% of annual production at affected sites. Same revisit condition as Molinder 2021. |
| `lauret2017_probabilistic-solar-qr.pdf` — Lauret, David, Pedro, *Probabilistic solar forecasting using quantile regression models*, Energies 10, 2017 · [10.3390/en10101591](https://doi.org/10.3390/en10101591) | **Not relevant to the horizon or scale.** Linear quantile regression for 1–6 h-ahead irradiance at two single sites (La Réunion and a US desert station), using ground measurements plus IFS day-ahead forecasts as inputs. Its finding that NWP inputs sharpen intra-day intervals without hurting reliability, and that site variability drives quality, does not transfer to a day-ahead regional target. |
