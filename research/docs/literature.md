# Literature review — day-ahead wind and solar forecasting

Compiled 2026-09-21 for `research/README.md`. Scope: what the published record, vendor
documentation and grey literature say about the problems the README lists.

**How to read this file**

- Every DOI was resolved against Crossref (journal articles) or DataCite (arXiv) on the day
  of writing; the title and year returned matched. Where no DOI exists (NeurIPS, JMLR, data
  documentation) the URL is given instead.
- Each entry states what was actually read: **full text** (or substantial parts),
  **abstract**, **docs page**, or **metadata only**. For *metadata only* entries the summary
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
| ECMWF IFS ENS archive as Zarr, 51 members, 100 m wind, init times from 2024-04-01 | P1 | §4, dynamical.org | archive covers the whole backtest window, unlike MEPS; check init hour vs the 10:00 cutoff, 3-hourly steps, ~20 km grid |
| Open-Meteo **Single Runs API** — `run=` parameter, IFS HRES runs at 00/06/12/18 from 2024-03-14 | P2 | §4, Open-Meteo docs | fixes the vintage step for ECMWF only; other models only from 2026-04-02 |
| Recalibrate quantiles with a second-stage quantile regression / conformal layer, weighted by context | P1 | §3, Lindberg 2024; Moradi 2025; Romano 2019 | conformal gives marginal coverage; the high-wind gap needs group-conditional methods |
| Coverage-by-output charts can mislead if binned by *realised* output | P1, EVAL | §9, Lerch 2017 | check how `coverage_by_output.png` bins |
| Neighbourhood pseudo-ensemble from a deterministic 2.5 km run | P1 | §3, Molinder 2018 | icing study, two weeks of data; still under-dispersive |
| Simulated fleet output from reanalysis as an independent ceiling | P3 | §6, Olauson; Staffell | needs per-period bias correction |
| ENTSO-E `A03` step-curve encoding under-reports if parsed naively | P3 | §6, Nicolaysen 2026 | brand-new single-author preprint, unreviewed |

**Two results that corroborate what the README already found.** Lindberg et al. (2024) used
only the MEPS control member because MEPS's ensemble size was inconsistent over their period,
which is the same publication-history problem `reports/meps_archive.md` hit. Meisenbacher et
al. (2025) found plain power-curve models beat deep autoregressive models when shutdowns are
irregular, in line with "physics gets you most of the way".

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

### Review on probabilistic forecasting of wind power generation
Zhang, Wang, Wang · Renew. Sustain. Energy Rev. 32, 2014 ·
[10.1016/j.rser.2014.01.033](https://doi.org/10.1016/j.rser.2014.01.033) · *read: metadata + search excerpt*

Survey of parametric, non-parametric and scenario methods and of how to verify them.
- Splits the chain into scenario generation, modelling and post-processing, and warns that optimising each step separately need not optimise the whole.
- → Supports treating calibration as its own stage after the quantile model rather than hoping the model gets it right.

### The future of forecasting for renewable energy
Sweeney, Bessa, Browell, Pinson · WIREs Energy Environ. 9(2), 2020 ·
[10.1002/wene.365](https://doi.org/10.1002/wene.365) · *read: abstract*

Overview of wind and solar forecasting from minutes to days ahead, then a look at where it is heading.
- Future products need probabilistic information, delivered in a form tailored to the end user's decision problem and risk constraints.
- → Supports reporting a range rather than a point, and choosing which quantiles to publish by use rather than by convention.

### Current methods and advances in forecasting of wind power generation
Foley, Leahy, Marvuglia, McKeogh · Renewable Energy 37(1), 2012 ·
[10.1016/j.renene.2011.05.033](https://doi.org/10.1016/j.renene.2011.05.033) · *read: metadata only*

Overview of physical, statistical and hybrid wind forecasting.
- NWP is the dominant input at day-ahead horizons; the statistical layer's job is the weather-to-power conversion.
- → Background for the README's finding that physics gets you most of the way.

### Probabilistic forecasting
Gneiting, Katzfuss · Annu. Rev. Stat. Appl. 1, 2014 ·
[10.1146/annurev-statistics-062713-085831](https://doi.org/10.1146/annurev-statistics-062713-085831) · *read: metadata only*

Statistical foundations of probabilistic forecasting.
- Central principle: maximise sharpness subject to calibration.
- → Frames problem 1 precisely: the ranges are sharp but not calibrated, so calibration comes first.

### IEA Wind Recommended Practice for the Implementation of Renewable Energy Forecasting Solutions
IEA Wind TCP Task 36/51 · Elsevier, 2023 ·
[10.1016/C2021-0-03549-5](https://doi.org/10.1016/C2021-0-03549-5) · *read: metadata only*

Industry guidance on choosing, trialling and evaluating forecast solutions.
- Covers evaluation design, benchmarks and probabilistic forecast verification for operational use.
- → Worth a read for how it treats "what was known at issue time" when trialling vendors (relevant to the TSO-forecast vintage caveat). Free earlier editions are hosted by IEA Wind Task 36 — see §11.

---

## 2. Quantile and tree-based models

### Probabilistic wind power forecasts using local quantile regression
Bremnes · Wind Energy 7(1), 2004 · [10.1002/we.107](https://doi.org/10.1002/we.107) · *read: abstract*

Probabilistic wind power forecasts by local quantile regression, applied to a Norwegian wind farm.
- No distributional assumptions and flexible inclusion of predictive information.
- Quantile forecasts carry exactly the information needed for optimal economic decisions in some settings.
- Lindberg et al. (§3) credit Bremnes with the idea of post-processing forecasts by quantile regression.

### Quantile regression forests
Meinshausen · J. Mach. Learn. Res. 7, 2006 · [jmlr.org/papers/v7/meinshausen06a.html](https://jmlr.org/papers/v7/meinshausen06a.html) (no DOI) · *read: metadata only*

Random forests that keep leaf observations so any quantile of the conditional distribution can be read off.
- One fitted model gives all quantiles, and they cannot cross.
- → A useful cross-check against LightGBM quantile models; it is the model the Swedish SE3 studies used (§3, §5).

### Probabilistic gradient boosting machines for GEFCom2014 wind forecasting
Landry, Erlinger, Patschke, Varrichio · Int. J. Forecasting 32(3), 2016 ·
[10.1016/j.ijforecast.2016.02.002](https://doi.org/10.1016/j.ijforecast.2016.02.002) · *read: metadata only*

Boosted-tree entry to the GEFCom2014 wind track.
- Direct precedent for the approach the project ships (boosted trees, full range of outcomes).
- → Compare its feature set against the 87 inputs.

### Very-short-term probabilistic forecasting of wind power with generalized logit-normal distributions
Pinson · J. R. Stat. Soc. C 61(4), 2012 ·
[10.1111/j.1467-9876.2011.01026.x](https://doi.org/10.1111/j.1467-9876.2011.01026.x) · *read: abstract*

Predictive densities for double-bounded wind power: mixtures of generalized logit-normal distributions plus probability masses at the bounds, with recursively updated parameters.
- Beats normal and beta assumptions, shown on 10-minute-ahead forecasts at Horns Rev (Denmark).
- → Very-short-term, so the dynamics don't transfer, but the point about respecting the [0, 1] bounds does: your target is a share of installed capacity, and bands should not spill past zero or full output.
- → A parametric alternative to compare against, not a replacement for the quantile models.

### Conditional prediction intervals of wind power generation
Pinson, Kariniotakis · IEEE Trans. Power Syst. 25(4), 2010 ·
[10.1109/tpwrs.2010.2045774](https://doi.org/10.1109/tpwrs.2010.2045774) · *read: metadata only*

Prediction intervals for wind power conditioned on forecast information (title only; I did not check the method).

### On-line assessment of prediction risk for wind power production forecasts
Pinson, Kariniotakis · Wind Energy 7(2), 2004 ·
[10.1002/we.114](https://doi.org/10.1002/we.114) · *read: abstract*

Resampling-based confidence intervals with no distributional assumption on errors, refined by a "meteo-risk index" (MRI).
- Errors are classified with fuzzy sets to respect the non-linear power curve and the cut-off effect.
- The MRI reflects the spread of the available NWP forecasts, and the abstract reports a linear relation between it and the resulting prediction error.
- Intervals are narrowed in stable weather; the index is also offered as a warning signal for operators.
- → Your worst day was "confidently mistaken" with an ordinary-width band. A spread-based risk index is the classical remedy, and it needs only multi-model spread, which you already have from three models.
- → Also a light-weight test of whether spread predicts error before adding more ensemble data.

---

## 3. Calibration, spread and conformal methods (P1)

### Quantifying the value of probabilistic forecasts when trading renewable hybrid power parks in day-ahead markets: A Nordic case study
Lindberg, Zhu, Widén · Renewable Energy 237, 2024 ·
[10.1016/j.renene.2024.121617](https://doi.org/10.1016/j.renene.2024.121617) · *read: full text (abstract, data and methods sections)*

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
[10.48550/arXiv.1905.03222](https://doi.org/10.48550/arXiv.1905.03222) · *read: metadata only*

Widens or narrows a quantile-regression band by a margin estimated on held-out data, giving finite-sample marginal coverage.
- Keeps the adaptivity of quantile regression and adds a coverage guarantee.
- → Turns the observed 74% into a 80% target by construction, but only on average: the high-wind shortfall needs the group-conditional variants below.
- → Guarantee assumes exchangeability; time series drift, so the calibration set should be the most recent stretch, not random.

### Conformal Prediction: A Gentle Introduction
Angelopoulos, Bates · Found. Trends Mach. Learn. 16(4), 2023 ·
[10.1561/2200000101](https://doi.org/10.1561/2200000101) · *read: metadata only*

Practical tutorial with recipes for regression intervals.
- Good single reference for implementing split conformal and understanding what "coverage" it does and does not promise.

### The limits of distribution-free conditional predictive inference
Barber, Candès, Ramdas, Tibshirani · Inf. Inference 10(2), 2021 ·
[10.1093/imaiai/iaaa017](https://doi.org/10.1093/imaiai/iaaa017) · *read: metadata + search excerpt*

Shows that exact coverage conditional on the covariates is impossible without assumptions or trivial intervals.
- → Don't aim for "80% at every output level"; aim for coverage within pre-chosen groups (predicted-level bins, season).

### Conformal prediction with conditional guarantees
Gibbs, Cherian, Candès · arXiv 2023 ·
[10.48550/arXiv.2305.12616](https://doi.org/10.48550/arXiv.2305.12616) · *read: metadata + search excerpt*

Finite-sample coverage over a chosen class of covariate-defined groups, not just on average.
- → A principled version of "calibrate separately for high-wind hours"; groups could be bins of predicted output, season, and spread.

### Enhanced renewable energy forecasting using context-aware conformal prediction
Moradi, Tanneau, Zandehshahvar, Van Hentenryck · arXiv 2025 (rev. 2026) ·
[10.48550/arXiv.2510.15780](https://doi.org/10.48550/arXiv.2510.15780) · *read: abstract*

Weights the calibration set toward historical hours similar to the target forecast condition; model-agnostic, no retraining. Tested on day-ahead solar (MISO, ERCOT, SPP).
- Improves the reliability-versus-width trade-off against plain conformal baselines.
- → Weight past hours by similarity in predicted output, wind regime and season to attack the high-wind under-coverage. Evidence is for solar; wind is untested.

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

### Probabilistic forecasting of wind power production losses in cold climates: a case study
Molinder, Körnich, Olsson, Bergström, Sjöblom · Wind Energy Sci. 3, 2018 ·
[10.5194/wes-3-667-2018](https://doi.org/10.5194/wes-3-667-2018) · *read: abstract + results*

Swedish icing losses from an 11-member 2.5 km ensemble (HarmonEPS) and a neighbourhood of 25 grid points, over two weeks.
- Ensemble + neighbourhood cut production-loss error from 26% to 21%; spread–skill correlation rose from about 0.3 (neighbourhood only) to about 0.7.
- Forecasts stayed under-dispersive: actual error exceeded predicted spread.
- → With no usable ensemble, the spread of nearby grid points in a deterministic 2.5 km run is a candidate pseudo-ensemble for MEPS-det, which you already extract.
- → Two weeks and an icing target, so evidence of principle only.

---

## 4. Weather data: run addressing, vintage and ensemble archives (P1, P2)

### Open-Meteo Single Runs API
Open-Meteo documentation · [open-meteo.com/en/docs/single-runs-api](https://open-meteo.com/en/docs/single-runs-api) · *read: docs page*

Returns the full horizon of one archived model run, selected with a required `run=YYYY-MM-DDTHH:MM` parameter.
- ECMWF IFS HRES (9 km) individual runs at 00/06/12/18 UTC archived from 2024-03-14; most other models only from 2026-04-02.
- The docs warn that initialisation time differs from public availability (about 4–6 h for global models).
- → Would give a run-addressed IFS and remove the lead-hour-34 step for that model without the MEPS download. Your reports record that a `*_previous_run1` parameter was rejected, but do not mention this endpoint.
- → GFS and ICON-EU would not be run-addressable across the backtest window, so the three-model set would become mixed. Also confirm the 9 km HRES matches the 0.25° `ecmwf_ifs025` you pinned before swapping it in.
- → Pricing and free-tier limits were not visible on the page; check before planning a two-year pull.

### Open-Meteo Previous Runs API and maintainer discussion #1023
Open-Meteo documentation · [Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api) · [discussion](https://github.com/open-meteo/open-meteo/discussions/1023) · *read: docs page + discussion*

Fixed lead-time offsets (`_previous_day1` … `_previous_day7`); most models archived from January 2024.
- The Historical Forecast API instead stitches the first hours of every run, so it is not what a day-ahead model sees.
- The maintainer notes processing delay (about 5 h 20 min for ECMWF IFS) is folded into the offset, and that combining offsets from several runs still worked well for day-ahead ML.
- → Confirms your finding that this API cannot be addressed by run; supports the information-age bookkeeping you already do.

### ECMWF IFS ENS 15-day forecast (Zarr archive)
dynamical.org · [catalog page](https://dynamical.org/catalog/ecmwf-ifs-ens-forecast-15-day-0-25-degree/) · [AWS registry](https://registry.opendata.aws/dynamical-ecmwf-ifs-ens/) · *read: docs pages*

51-member ECMWF ensemble at 0.25°, init times from 2024-04-01, updated every 24 h, CC BY 4.0, no authentication.
- Includes 100 m wind components (`wind_u_100m`, `wind_v_100m`), 2 m temperature, cloud and radiation.
- Lead times: 3-hourly to 144 h, 6-hourly beyond.
- → This is the instrument `meps_archive.md` guessed at ("most plausibly the ECMWF ENS archive"): it spans the whole 546-day window, so spread would not switch on and off.
- → Checks before committing: which UTC init hour is stored and whether its real-world availability precedes 10:00 market time; 3-hourly steps need interpolation to hourly; 0.25° is coarse next to MEPS; ECMWF model upgrades within the window could shift spread and bias, the same era risk you found in MEPS.

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
Dantas, Browell · arXiv 2025 · [10.48550/arXiv.2502.11960](https://doi.org/10.48550/arXiv.2502.11960) · *read: abstract*

One model from 6 to 162 h ahead on 73 GB wind farms over five years, modelling weather uncertainty and weather-to-power uncertainty separately.
- Weather-to-power uncertainty dominates at short lead times; weather forecast uncertainty dominates at longer ones, with the crossover earlier offshore than onshore.
- → Supports letting the interval width depend on lead hour, which your +35% step at lead 34 suggests it should.

### Probabilistic wind power forecasting with tree-based machine learning and weather ensembles
Bruninx, van Binsbergen, Verstraeten, Nowé, Helsen · arXiv 2026 (rev. July) ·
[10.48550/arXiv.2602.13010](https://doi.org/10.48550/arXiv.2602.13010) · *read: abstract*

Four years of Belgian offshore wind farms; compares conformalized quantile regression, natural gradient boosting and conditional diffusion on top of tree models.
- Using multiple NWP providers instead of one improved point accuracy by 17% on average.
- Diffusion was best (about 5% lower MAE and 12% lower CRPS than the probabilistic baseline); all three beat a Gaussian-process baseline.
- → Independent support for keeping several NWP providers. Offshore, single farm cluster: not directly comparable to SE3.

### Machine learning forecasts of Scandinavian numerical weather prediction wind model residuals with control theory for wind energy
Chen, Zhang, Birkelund · Energy Rep. 8, 2022 · [10.1016/j.egyr.2022.08.105](https://doi.org/10.1016/j.egyr.2022.08.105) · *read: metadata only*

Forecasts the errors (residuals) of a Scandinavian NWP wind model with ML; a companion statistical analysis of the residuals is at [10.1016/j.egyr.2022.07.080](https://doi.org/10.1016/j.egyr.2022.07.080).
- → Candidate for a residual-correction step on the NWP wind itself, before the power curve. I did not read it, so which NWP model, sites and horizons are unknown.

---

## 5. Nordic and Swedish (SE3) studies

### Day-ahead probabilistic forecasting at a co-located wind and solar power park in Sweden: Trading and forecast verification
Lindberg, Lingfors, Arnqvist, van der Meer, Munkhammar · Adv. Appl. Energy 9, 2023 ·
[10.1016/j.adapen.2022.100120](https://doi.org/10.1016/j.adapen.2022.100120) · *read: search excerpt only (full text returned 403)*

Same SE3 park as Lindberg 2024; QRF post-processed with quantile regression on MEPS inputs.
- The 2024 paper attributes the finding that QRF calibration was insufficient to an earlier Lindberg et al. paper, presumably this one; I could not confirm which.
- → Get the full text: see §11.

### Forecasting onshore wind generation in European bidding zones using deep learning
Kean, O'Sullivan · npj Clean Energy, 2026 ·
[10.1038/s44406-026-00036-6](https://doi.org/10.1038/s44406-026-00036-6) · *read: abstract (via Crossref); full text behind a login*

One network trained on 36 bidding zones (1.57 million hourly observations) using ENTSO-E and Open-Meteo data; reports beating TSO forecasts by 25.65% RMSE and 26.56% MAE across 30 zones.
- Gains attributed to data volume: models trained per zone on the same data did worse.
- → Same data stack as this project, so the most direct external comparison there is.
- → Pooling neighbouring zones is a way around having only two years of SE3 history.
- → It reports large gains over the TSO forecast, while your README warns the archived TSO series is a revised version. I could not check how either paper obtained the TSO forecast or whether the Open-Meteo weather was leak-free. Read the methods before relying on either comparison.

### Cold Climate Wind: Challenges, Technological Solutions and Policy
Karlsson et al. · WIREs Energy Environ., 2026 · [10.1002/wene.70025](https://doi.org/10.1002/wene.70025) · *read: metadata only*

Review of cold-climate wind, including icing.
- → If the 13 February 2026 miss coincided with cold or icing conditions, this and the Molinder papers are the place to start. That is a hypothesis to test against temperature on that day, not a finding.

### Probabilistic forecasting of wind turbine icing related production losses using quantile regression forests
Molinder et al. · Energies 14(1), 2021 · [10.3390/en14010158](https://doi.org/10.3390/en14010158) · *read: metadata only*

QRF applied to Swedish icing-related losses.
- Another data point for QRF in Sweden.

---

## 6. Capacity denominator, data quality and reanalysis (P3)

No paper found addresses a falling ratio of rolling peak generation to registered capacity directly. The entries below are the closest tools for isolating cause.

### Modelling the Swedish wind power production using MERRA reanalysis data
Olauson, Bergkvist · Renewable Energy 76, 2015 ·
[10.1016/j.renene.2014.11.085](https://doi.org/10.1016/j.renene.2014.11.085) · *read: metadata only*

### ERA5: The new champion of wind power modelling?
Olauson · Renewable Energy 126, 2018 ·
[10.1016/j.renene.2018.03.056](https://doi.org/10.1016/j.renene.2018.03.056) · *read: metadata only*

Simulate Swedish national and zonal wind output from reanalysis and compare it with reported generation; the second paper argues ERA5 is a better base than MERRA.
- → Building a simulated fleet from a fixed turbine mix gives an independent meteorological ceiling. If that simulated ceiling ratio stays flat while reported output falls, the cause is non-meteorological (register, reporting or curtailment); if it also falls, look at turbine layout and wakes. This matches the untracked `era5_*` files in your working tree.

### Using bias-corrected reanalysis to simulate current and future wind power output
Staffell, Pfenninger · Energy 114, 2016 ·
[10.1016/j.energy.2016.08.068](https://doi.org/10.1016/j.energy.2016.08.068) · *read: metadata only*

The Renewables.ninja method: reanalysis wind speeds corrected against national generation before conversion to power.
- Reanalysis has systematic bias that must be corrected per country, so a fixed correction applied across years can itself create drift.
- → Estimate the correction on a window and test on others, so drift is not absorbed into the calibration.

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
[10.48550/arXiv.2609.16152](https://doi.org/10.48550/arXiv.2609.16152) · *read: abstract; unreviewed preprint*

Reports that hourly series use step curves (`A03`) in which missing positions imply the previous value holds, so a parser that sums only the listed points under-reports, by 22.6% for one Finnish unit in 2021.
- Also studies register vintages and production-type labels.
- → Check that the ingest fills `A03` gaps, and whether the share of elided points changed over 2018–2025. It is a cheap rule-out for P3, not a known cause. Single author, three days old: weigh accordingly.

### Modelling regional solar photovoltaic capacity in Europe: A data-driven approach for disaggregation, benchmarking, and forecasting
Alghanem, Buckley · Energy Rep. 14, 2025 · [10.1016/j.egyr.2025.07.010](https://doi.org/10.1016/j.egyr.2025.07.010) · *read: metadata only*

Data-driven disaggregation and forecasting of PV capacity by region.
- → Solar analogue of P3: the capacity denominator for PV is itself modelled, so start solar with a plan for it.

---

## 7. Regional aggregation, high wind and shutdowns

### Probabilistic forecasting of temporal trajectories of regional power production — Part 1: Wind
Thorarinsdottir, Løland, Lenkoski · arXiv 2019 ·
[10.48550/arXiv.1903.01186](https://doi.org/10.48550/arXiv.1903.01186) · *read: abstract*

Bayesian model for hourly German regional wind: cubic transform of power, multivariate Gaussian errors with temporal correlation, NWP covariates, lead times of several days.
- Modelling temporal error correlation was important for calibrated, skilful trajectories.
- → Your worst day was wrong by about 520 MW for 24 hours straight: errors are strongly autocorrelated within a day, so per-hour bands understate whole-day risk. Matters if outputs feed a daily briefing or bidding curve.

### On autoregressive deep learning models for day-ahead wind power forecasts with irregular shutdowns due to redispatching
Meisenbacher et al. · at – Automatisierungstechnik 73, 2025 ·
[10.1515/auto-2024-0171](https://doi.org/10.1515/auto-2024-0171) · *read: abstract (arXiv version)*

Compares three autoregressive deep models with power-curve models on onshore data that include redispatch shutdowns.
- Simple power-curve methods had lower error, needed less data cleaning and were cheaper to run.
- Shutdown interventions corrupt any feature built on recent generation.
- → Supports both your physics-first design and caution around the lagged-generation features.
- → Swedish congestion-driven down-regulation would behave the same way. I found no citable source for its volume in SE3; Svenska kraftnät's balancing data is the place to look.

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
[10.48550/arXiv.1903.01188](https://doi.org/10.48550/arXiv.1903.01188) · *read: search excerpt*

Fully probabilistic hourly model for spatially aggregated PV with NWP covariates and lead times up to several days; the companion of Part 1, which uses German data.
- → Ready-made structure for the German solar track; confirm the data region in the paper.

### Regional PV power prediction for improved grid integration
Lorenz, Scheidsteger, Hurka, Heinemann, Kurz · Prog. Photovolt. 19(7), 2011 · online 2010 ·
[10.1002/pip.1033](https://doi.org/10.1002/pip.1033) · *read: abstract*

ECMWF-based regional PV forecasts up to two days ahead, hourly, upscaled from a representative set of PV systems; evaluated on two German TSO control areas (July 2009 – April 2010).
- Operational RMSE was 4–5% of nominal power for intra-day and day-ahead horizons; a modified upscaling that models the spatial distribution of nominal power on a 1° × 1° grid improved on it.
- → A useful order-of-magnitude yardstick for German solar, though from 2009–10 and much lower PV penetration.
- → The capacity-distribution idea mirrors your capacity-weighted wind locations.

### Data-driven upscaling methods for regional photovoltaic power estimation and forecast using satellite and numerical weather prediction data
Pierro et al. · Sol. Energy 158, 2017 ·
[10.1016/j.solener.2017.09.068](https://doi.org/10.1016/j.solener.2017.09.068) · *read: search excerpt*

Upscaling from reference plants to a region using satellite and NWP inputs.
- → Solar equivalent of the wind upscaling choices in §7.

### A probabilistic approach to the estimation of regional photovoltaic power production
Saint-Drenan et al. · Sol. Energy 147, 2017 ·
[10.1016/j.solener.2017.03.007](https://doi.org/10.1016/j.solener.2017.03.007) · *read: metadata only*

Probabilistic estimate of regional PV production.
- → Relevant because the German TSO "actual" solar figure is itself an estimate, so the target carries its own uncertainty.

### Review on probabilistic forecasting of photovoltaic power production and electricity consumption
van der Meer, Widén, Munkhammar · Renew. Sustain. Energy Rev. 81, 2018 ·
[10.1016/j.rser.2017.05.212](https://doi.org/10.1016/j.rser.2017.05.212) · *read: metadata only*

### Probabilistic solar forecasting using quantile regression models
Lauret, David, Pedro · Energies 10(10), 2017 · [10.3390/en10101591](https://doi.org/10.3390/en10101591) · *read: metadata only*

### A review of solar forecasting, its dependence on atmospheric sciences and implications for grid integration: Towards carbon neutrality
Yang et al. · Renew. Sustain. Energy Rev. 161, 2022 · [10.1016/j.rser.2022.112348](https://doi.org/10.1016/j.rser.2022.112348) · *read: metadata only*

Reviews and a quantile-regression study for PV.
- Standard practice is to model a clear-sky index rather than raw output, so the daily cycle does not dominate the error.
- The Yang review pushes for a common verification practice.

### Variable renewable energy forecasting in Germany: Reassessing simplicity with Bayesian-optimised multilayer perceptrons
Wanek · Renewable Energy 262, 2026 · [10.1016/j.renene.2026.125409](https://doi.org/10.1016/j.renene.2026.125409) · *read: title only; ScienceDirect returned 403*

Recent German wind and solar forecasting study.
- → Likely a current German benchmark; get the full text before choosing baselines (§11).

---

## 11. Sources I could not access

Please fetch these manually if you want them read; I can then summarise them.

| source | where | why it matters |
|---|---|---|
| Lindberg et al. 2023, *Adv. Appl. Energy* | [doi.org/10.1016/j.adapen.2022.100120](https://doi.org/10.1016/j.adapen.2022.100120) (ScienceDirect, 403) | SE3 QRF calibration results, and how MEPS was handled |
| Kean & O'Sullivan 2026, *npj Clean Energy* | [doi.org/10.1038/s44406-026-00036-6](https://doi.org/10.1038/s44406-026-00036-6) (login redirect) | How Open-Meteo weather and TSO forecasts were obtained (leakage? vintage?); results for SE zones |
| Wanek et al. 2026, *Renewable Energy* | [doi.org/10.1016/j.renene.2026.125409](https://doi.org/10.1016/j.renene.2026.125409) (403) | German VRE benchmark |
| Olauson 2015 and 2018; Staffell & Pfenninger 2016 | DOIs in §6 | Method details for the P3 reanalysis check |
| Pinson & Kariniotakis 2010; Pinson 2012; Bremnes 2004 | DOIs in §2 | Interval and distribution methods for P1 |
| IEA Wind Recommended Practice, evaluation and forecast-trial parts | IEA Wind Task 36 pages at iea-wind.org (free PDFs of earlier editions, as I recall) | Evaluation and vendor-trial conventions |
| Svenska kraftnät or Energimyndigheten statistics on wind down-regulation and curtailment in SE3 | not found | Would test the redispatch and curtailment explanation for P3 and high-wind misses |
| ECMWF ENS archive init hour and cycle history | dynamical.org docs | Decide whether the 00 UTC run is available before 10:00 market time |

## 12. Gaps

- **P3 (capacity drift):** no paper found on the specific symptom. The section-6 material narrows the search but does not explain it.
- **P4 (15-minute):** thin peer-reviewed coverage; expect to design this from first principles and the metrics vocabulary in §8.
- **Swedish curtailment and redispatch magnitudes:** no citable source found.
- **Machine-learning weather models** (AIFS, GenCast, Google WeatherNext) appear as ensembles in Open-Meteo's Ensemble API listing. The constraint is archive depth, not quality, so I did not review them further.
