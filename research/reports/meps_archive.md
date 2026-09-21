# Phase 6 spike — Is a true ensemble available retroactively?

**Timeboxed, 2026-09-20.** Self-archiving was deliberately deferred, so the only route
to a genuine ensemble in v1 is someone else's archive. MET Norway's MEPS is the
candidate: 2.5 km over the Nordics, 30 members, leads past 60 h, free, no registration.

## What is there

`https://thredds.met.no/thredds/catalog/meps25epsarchive/` holds **2016 through 2026** —
far deeper than the 12–18 months the plan hoped for.

Confirmed by OPeNDAP header inspection:

| date sampled | product | ensemble | lead steps | grid |
|---|---|---|---|---|
| 2024-06-01 | `meps_lagged_6_h_vc_2_5km` | **`ensemble_member = 30`** | 62 | `x = 37977, y = 1` (packed cross-section, not a plain lat/lon grid) |
| 2026-09-01 | `meps_det_2_5km` | none — deterministic | 67 | `x = 949, y = 1069` at 2.5 km |

Lead coverage is not a problem: 62–67 steps comfortably spans the +22…+47 h window the
task needs from a 00z run.

## The catch, which is the version-drift hazard the plan named

**The product mix changes across the archive.** The 2024 sample carries a 30-member
lagged ensemble; the 2026 sample carries only deterministic runs under a different
filename. A model trained across that boundary would be learning the archive's
publication history, not the atmosphere — the same class of error as training across a
reporting-methodology change.

There is a second complication. The 30-member file is a `_vc_` product with `y = 1` and
`x = 37977`: a packed representation, not the plain projected grid the deterministic
files use. Extracting the eight SE3 cluster points from it needs its own coordinate
handling, which is not the same code path as the deterministic files.

## Verdict: conditional GO, and not free

The ensemble genuinely exists retroactively, which is the question the spike was asked.
But "download and use it" is not the shape of the work. What it actually needs:

1. Map the product mix era by era across 2016–2026 — which filenames, which member
   counts, which grid representation, and where each boundary falls.
2. Write the packed-grid point extraction, separate from the deterministic path.
3. Carry the era as a categorical feature and as a reporting segment, so a boundary
   shows up in the metrics rather than hiding in them.
4. Estimate extraction throughput before committing: 8 points x 30 members x ~48 steps
   x several variables x ~900 days over OPeNDAP is not a small pull.

That is a day or two of work, not an afternoon, and it is worth doing — 2.5 km resolves
Swedish terrain and coastal effects that 0.25 ° global models cannot, and the current
multi-model spread rests on only three deterministic providers.

## What v1 does in the meantime

Multi-model spread across `ecmwf_ifs025`, `gfs025` and `icon_eu` carries the uncertainty
signal, and the conformal layer carries the calibration. The leaderboard shows this is
adequate but not sufficient: `lightgbm_quantile` is still underdispersed at 0.737 against
a nominal 0.80, and flow-dependent ensemble spread is the most likely thing to close that
gap properly rather than by post-hoc widening.

## Amendment, 2026-09-21 — MEPS is now also the vintage fix

The spike was commissioned to answer one question: is a real ensemble available
retroactively? Phase 5 gave it a second, larger job.

Open-Meteo's Previous Runs API is addressable only in whole days, so the back half of
every delivery day is served by a forecast 24 h older than the physics requires. The cost
is measured and large — a **+35% step in nMAE at lead hour 34**, on 13 of 24 delivery
hours (`openmeteo_vintage.md`, `modelling.md`). There is no fix inside that API; a
`*_previous_run1` parameter was probed and does not exist.

MEPS files on thredds are addressed **by run initialisation**. A single 00z run covers
the whole +22…+47 h window, which removes the step by construction. So the two
justifications now stack: 2.5 km resolution and 30 members for the underdispersion, and
run addressing for the vintage step. Either alone would be worth a day or two; together
they make this the highest-value item outstanding.

**Recommended ordering.** Do the MEPS integration *before* starting DE-LU solar. It
addresses two measured deficiencies in the current model, whereas solar starts a second
track whose scaffolding already exists and can wait.
