# Historical demo release

Local release review: 2026-10-26. This is milestone 1 of the
[roadmap](../ROADMAP.md). Public deployment and anonymous HTTPS checks remain
with the project owner.

## What this release presents

The first view opens on **SE3 onshore wind, delivery 2026-09-19**, using the
completed final evaluation. The chart compares the hourly-trained model repeated
over quarter-hours with the physical power-curve reference, actuals and prediction
intervals. Performance keeps development and final results separate; Methods
describes inputs, source resolution and the 09:00 UTC information cutoff.

German solar, load and price results remain available through the same sidebar.
The European coverage map provides context; imported observations do not imply
forecast or publication coverage. The next research target is SE4 wind, after the
shared product and daily SE3 workflow in milestone 2.

This is a historical website. The bundled file index was exported at
**2026-10-23T15:00:31.076936+00:00**. SE3's final evaluation covers 2026-03-20 through
2026-09-19, with 182 of 184 complete days. Later saved issues retain their recorded
publication times and statuses. The export date does not imply current forecasts
or reliable daily updates.

## Release files and checks

`scripts/prepare_demo.py` checks all 13 Parquet files named in the current file
index, including the checksum in each filename. They are present and tracked in
Git. It copies only the four forecast pages, their shared presentation modules,
three JSON summaries, map outlines and indexed results. Older local exports,
research data, model training, the database application and chat are outside the
runtime image. Existing evaluations, model version records and their recorded
source files are unchanged.

Release inputs:

| File | SHA-256 |
|---|---|
| `src/grid_signals/app/assets/explorer/manifest.json` | `33cb51a6011dcd2a26b58bbf78846e07fdc6879d224591f5d1f6f67ecc97f98c` |
| `deploy/demo/requirements.txt` | `927abe6f7d4acd2bb31a0628e0695ba18a49b4e08aa911c82fbea530787aa7fc` |

The web image uses Python 3.12, a base-image digest and fully pinned dependencies
with package hashes. It runs as UID 10001. Its health check uses
`/_stcore/health` on port 8501. No environment keys, database, Prefect server,
forecast runner or persistent volume are required for this release.

Local validation on 2026-10-26:

- Full repository suite: **401 passed, 2 skipped**. The publication-status test
  now compares the displayed status and timestamp with the selected saved issue.
- Ruff lint and formatting pass; the existing `uv.lock` remains consistent.
- The built Linux/amd64 image passes both offline checks in
  `tests/demo_image_check.py`, with networking disabled and no database or API keys.
- The running container reports healthy. Browser review at 1440, 820 and 390 px
  widths shows the populated historical chart without horizontal page overflow.
  Navigation and the forecast CSV download work; no browser page errors occurred.
  The only external browser requests observed were Streamlit's navigation icons;
  no energy, weather or model API is called.

After the browser review, explanatory caption contrast was improved and the
Streamlit toolbar was set to viewer mode. The final image was rebuilt and checked.

Ruff checks the retained product code and tests. Standalone learning notebooks
are excluded until their move in milestone 2a. Three style-only rules are narrowly
exempted in two evaluated source files to preserve their recorded checksums;
other lint rules remain active. Formatting and style fixes elsewhere do not alter
model behaviour.

## Build and review the exact revision

From a clean checkout of the reviewed feature branch:

```bash
git status --short
git rev-parse HEAD
docker build -f Dockerfile.demo -t grid-signals-demo:local .
docker run --rm -i --network none --entrypoint python grid-signals-demo:local < tests/demo_image_check.py
docker run --rm -p 127.0.0.1:8502:8501 grid-signals-demo:local
```

Open http://localhost:8502. Check the initial SE3 chart, Performance, Models & data,
coverage, a German target, a missing-data area and CSV downloads. On mobile, open
the sidebar to change the shared selection. The offline image check also runs in
CI and exercises the pages without a network or credentials.

For the full repository checks (the existing database tests use local Docker):

```bash
uv sync --frozen --group research
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

## Owner deployment handoff

Use existing Dokploy capacity for one new web service:

1. Make the reviewed Git revision available to Dokploy when ready. No push or
   deployment is part of this local preparation.
2. Select **Dockerfile** build, repository root as build context and
   **`Dockerfile.demo`** as the Dockerfile. Use the reviewed revision rather than
   an unrelated branch tip. The original Compose files deploy a different system.
3. Set the internal service port to **8501**. Leave the image's startup command
   and health check in place. Supply no API keys or database settings; use no
   data mounts for this historical release.
4. Add the chosen public domain and enable HTTPS in Dokploy. A public domain
   routes to container port 8501; the local port 8502 above is only for preview.
5. From a signed-out browser, verify the HTTPS URL and health check, SE3's
   historical date and populated chart, all four pages, CSV downloads and German
   case studies. Check desktop and phone layouts, including the sidebar.
6. Record the public URL, deployed Git revision, image identity and date here,
   then complete the remaining roadmap checkbox. Rebuilding this image does not
   make forecasts fresh; daily production belongs to milestone 2.

The initial deployment should keep serving these bundled results if forecast
production is unavailable. Retain the prior image when updating the demo so it
can be restored if a newer release fails review.

## Removal work after this release

Milestone 2a saves original code, required data, evaluation results and publication
history before moving or removing components. It brings forecasting into the
installed package and one CLI, then removes the old database application,
briefing/chat pages and their runtime dependencies, duplicate forecast pages and
stale commands. Milestone 2b replaces the old flows and local forecast timers with
the tested Prefect forecast workflow. None is a prerequisite for hosting this
historical image.
