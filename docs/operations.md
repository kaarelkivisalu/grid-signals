# Local forecast operations

The [target architecture and migration plan](implementation-plan.md) replaces the two job
families. `grid-signals daily` and the existing Prefect flows operate PostgreSQL
market ingestion and briefings. The research `pipelines.daily` commands and local
timers below operate forecast publication. Neither currently calls the other.
These are current-state instructions, not two workflows to maintain indefinitely:
the target consolidates forecasting behind one package/CLI and Prefect lifecycle,
retires the original market application and removes forecast timers after cutover.

Run `uv run grid-signals ui` and open http://localhost:8501. The website reads
portable JSON/Parquet bundles independently of training. Atomic exports keep the last
results available during a production failure, with underlying forecast dates intact.

## Daily local trial

This is the existing trial mechanism, scheduled for retirement after Prefect
cutover. Do not add another active scheduler for the same production issues.

After `uv sync --group research`:

```bash
uv run python scripts/install_forecast_schedule.py
systemctl --user list-timers 'grid-signals-*'
```

The installer writes user services/timers for this checkout's virtualenv:

| Job | UTC | Behaviour |
|---|---|---|
| Save public forecasts | 08:55 | Preserve ENTSO-E wind/solar and load forecasts with raw metadata |
| Forecast | 09:00 | Refresh inputs; independently publish wind, solar, price and load; export snapshots |
| Score | 15:00 | Refresh actuals, score eligible first publications, update snapshots |

Deadline: 09:30 UTC. Missed timers run on resumption with their actual late or
retrospective status. Jobs have a 27-minute timeout and four-worker limits.
This is a local user-session schedule: the machine needs to be running, online
and able to execute user services. It is not an always-on server deployment.

Root `.env` supplies ENTSOE_API_KEY. No database or LLM key is needed. Failure
records store exception types, not credential-bearing HTTP URLs.

```bash
journalctl --user -u grid-signals-forecast.service --since today
journalctl --user -u grid-signals-capture.service --since today
journalctl --user -u grid-signals-score.service --since today
```

Evidence is under `research/data/operational/`: trial start, unchanged job records and saved public forecasts, raw XML/Parquet and renewable/price scorecards. Forecast Parquet archives
are under `research/data/predictions/`. Only first on-time issues are scored;
retries do not replace them. Scores await complete actual delivery days and remain
provisional as actuals change. The first scheduled trial issue is October 16;
today's late forecasts contribute no on-time evidence. Historical replay cannot
satisfy the 30-run integration gate.

Price publication now uses the declared LEAR baseline in
`research/configs/price_forward.yaml`, with hourly distributions repeated onto market
quarter-hours. Historical direct-quantile price forecasts remain archived as a
separate model version. Load is published with the candidate selected before its
final evaluation. Each product has its own forward scorecard.

Exact reproduction of the frozen load release requires its original local input
matrix. The model version record stores its checksum; newer API observations can contain revisions
and must not silently replace that matrix. The price-input experiment also requires
the original price cache. Portable website bundles include results, not training data.

Disable the schedule with:

```bash
systemctl --user disable --now grid-signals-capture.timer grid-signals-forecast.timer grid-signals-score.timer
```

## Refresh the historical explorer

The website has one shared market/date/target/model selection, full backtest
series and grouped diagnostics. Exporting reads **completed** research evaluations;
it never trains or reopens a sealed holdout:

```bash
PYTHONPATH=research/src uv run python -m renewable_forecast.reporting.export_explorer
```

The daily results-export job also runs this exporter. Files are named using checksums and the
file index (`manifest.json`) changes last, so a failed refresh leaves the previous generation readable.
Old generations can be removed when no running reader needs them. The web image
contains the exported result files, not the raw cache.

Generated Parquet exports are ignored by Git; the files already committed remain
tracked. When updating the bundled demo, commit the updated file index together
with its referenced result files. Use `git add -f` for newly generated files listed
in that index, rather than adding every older export in the directory.

Additional market observations are a bounded preview, separate from forecast inputs:

```bash
PYTHONPATH=research/src uv run python -m renewable_forecast.sources.market_context --start 2026-09-01 --end 2026-10-16
```

Use `--refresh` to replace this preview with a different range (maximum 90 days),
then export again. ENTSOE_API_KEY is read from the root .env. Current areas: DE-LU,
SE1–SE4, FI, EE, FR, NL, DK1 and DK2. Only DE-LU and SE3 have custom forecasts;
missing offshore observations prevent residual-load derivation. Historical charts
and metrics preserve source resolution, daylight eligibility and DST interval order.

[Volue examples](https://docs.volue.com/data-and-forecasts/volue-insight-timeseries/guides/examples)
informed the aligned fundamentals and forecast/actual comparison. The map uses
[entsoe-py bidding-zone geometry](https://github.com/EnergieID/entsoe-py/tree/master/entsoe/geo),
simplified for display. The local `market-areas.geojson` records the source package
version, per-file checksums and MIT license. Ireland/Northern Ireland use the
prior local Natural Earth outlines (public domain). Geometry is display context
rather than an operational boundary definition. The map includes all 39 areas in
the project's [SDAC registry](https://www.entsoe.eu/network_codes/cacm/implementation/sdac/).

## Public hosting

The presentation has a separate, non-root web-only image with pinned UI dependencies:

```bash
docker build -f Dockerfile.demo -t grid-signals-demo:local .
docker run --rm -p 127.0.0.1:8502:8501 grid-signals-demo:local
```

Open http://localhost:8502. The image includes the historical explorer and three summary bundles and omits the
legacy database/agent tools. Its build context excludes research data, secrets and
the virtualenv. The build checks every indexed Parquet file's checksum and copies
only those files into the final image. Old local exports remain untouched.
The base image is pinned by digest; `deploy/demo/requirements.txt` locks all web
dependencies with hashes. To intentionally update that dependency lock:

```bash
uv pip compile deploy/demo/requirements.in --python-version 3.12 --python-platform linux --generate-hashes --output-file deploy/demo/requirements.txt
```

Check the built image without networking or credentials:

```bash
docker run --rm -i --network none --entrypoint python grid-signals-demo:local < tests/demo_image_check.py
```

The same build and offline check run in CI. Refresh result bundles only when
intentionally publishing newer results, then rebuild. No refresh or training is
needed to deploy the saved historical release.

### Historical release and local review

Overview opens on **SE3, 2026-09-19** with a price graph and a combined fundamentals
graph. Area and date controls are visible. The saved selected model supplies at
most one forecast per product; products without a forecast show observations
only. Price uses EUR/MWh and the combined wind, solar and demand graph uses GW.
The sidebar links to Overview, Wind, Solar, Prices, Performance, Map and Models &
data. Area choices group country zones and nearby single-area markets, with
EE/LV/LT together. Buttons join edge to edge with square corners, small gaps
between groups and no country headings. Unsupported choices are greyed out for
each page.

Every page has one view, with its controls directly available and no Details
switch. Product pages retain aligned forecast/error panels and CSV downloads.
Performance exposes period and diagnostic controls; Models & data shows inputs,
fitting rules and limits. Delivery dates use a 160 px calendar field and Previous/
Next buttons that move between saved days; missing dates show an explicit empty
state. Map keeps all 39 SDAC areas visible and displays a full colour-coded table
that scrolls with the page. Areas link to Overview, evaluated cells to product
pages, and observation-only cells to Overview. Unavailable cells have no data link.
Forecast shading uses saved quantiles, not ensemble scenarios.

The bundled file index was exported at **2026-10-23T15:00:31.076936+00:00** and
references 13 checked, Git-tracked Parquet files. SE3's final evaluation covers
2026-03-20 through 2026-09-19, with 182 of 184 complete days. Later issues retain
their recorded publication times and statuses. The export date does not imply
current forecasts or reliable daily updates. Original evaluated results, model
version records and their source files are unchanged.

The 2026-10-26 portfolio checks passed: **407 tests, 2 skipped** before the latest
UI revisions. The grouped-area and Overview revision passed **45 focused tests**, Ruff lint and
formatting, two offline image checks and desktop/tablet/phone browser review at
1440, 820 and 390 px. Navigation and CSV downloads work without browser errors,
external requests or horizontal page overflow. Tests cover grouped choices,
one forecast per product, observation-only areas, all map links, the full zone
table, calendar navigation across missing days, preserved selections and aligned
error values. The publication-status test checks the selected issue.
Existing evaluated result files and model code were not changed.

Ruff excludes standalone learning notebooks until their move in milestone 2a.
Three style rules are narrowly exempted in two evaluated source files to keep
their recorded checksums intact; other lint rules remain active.

### Manual deployment steps for the owner

Public deployment and signed-out HTTPS verification remain open. Use the existing
Dokploy capacity for one web service:

1. Review the local demo at http://localhost:8502, then make the reviewed Git
   revision available to Dokploy when ready. Local preparation does not push code.
2. Choose a **Dockerfile** build with the repository root as context and
   **`Dockerfile.demo`** as the Dockerfile. Select the reviewed Git revision.
3. Set the internal port to **8501**, leaving the startup command and health check
   in place. No API keys, database settings or persistent volumes are needed.
   The image runs as UID 10001; its health endpoint is `/_stcore/health`.
4. Add the chosen domain and enable HTTPS in Dokploy, routing to container port
   8501. Port 8502 is only the local preview port.
5. Use a signed-out browser to check HTTPS, the historical SE3 date and chart,
   all product and evidence pages, German case studies, CSV downloads and phone navigation.
6. Record the public URL, Git revision, image identity and deployment date in this
   guide, then complete the remaining roadmap checkbox. Keep the previous image
   available for rollback when updating the demo.

The initial historical release needs only the web service. The target daily
deployment adds a Prefect server and forecast runner on the same host, with
persistent product data and a published-results volume mounted read-only in the
web container. See the [target deployment](implementation-plan.md#how-the-deployed-system-should-run).
The current Compose files do not implement that target; do not deploy the original
market stack unchanged as the forecast producer.

The earlier public URL returned 404; local evidence does not establish its cause.
No public deployment has changed. Deployment will be handled by the project owner
after local demo review. Existing Dokploy capacity is the first choice; reconsider
hosting only for a concrete operational or cost constraint. The
[roadmap](../ROADMAP.md) defines release acceptance; the
[historical direction review](project-direction-review.md) retains the comparison.
