# Grid Signals — Roadmap

Nordic-Baltic Energy Intelligence Agent: automated market analysis powered by structured data and LLM reasoning.

---

## MVP — Completed ✅

Milestones 1–3, 5–8 are done: project setup, PostgreSQL schemas (migrated from DuckDB), ENTSO-E ingestion, Open-Meteo weather, scheduling/CLI, LLM agent with tool use, daily briefing generation, testing & docs.

### Milestone 4: Data Ingestion — Baltic/Nordic System Data

**Goal:** Pull supplementary real-time and system-level data.

- [ ] Elering (Estonian TSO) API:
  - System balance and frequency
  - Real-time production/consumption
  - Cross-border flows (EE-FI, EE-LV)
  - NPS (Nord Pool Spot) prices for EE
- [ ] Fingrid (Finnish TSO) API:
  - Nuclear production (Olkiluoto status is a key market driver)
  - Wind power production (actual vs forecast)
  - System state and frequency
  - Requires free API key registration
- [ ] Evaluate: Litgrid/AST APIs for LT/LV (less mature, may skip)

**Note:** Some of this data overlaps with ENTSO-E. The TSO APIs are useful for near-real-time data (updated every few minutes) vs ENTSO-E (hourly/daily).

---

## Post-MVP — Future Directions

### Direction A: Interactive Chat Interface ✅ (basic)

- [x] Streamlit chat page with `st.chat_input()` / `st.chat_message()`
- [x] Tool call visibility in expanders, token/cost display
- [ ] Persistent conversation context — the agent remembers what was discussed earlier in the session (requires `Agent.run()` refactor to accept message history)

### Direction B: Anomaly Detection & Real-Time Alerts

Shift from scheduled briefings to continuous monitoring with alerts when something unusual happens.

- Build a statistical baseline model: expected price given wind forecast, temperature, outage schedule, day-of-week, season
- Detect significant deviations from the baseline in near-real-time
- LLM explains the anomaly: what's unusual and what might be causing it
- Alert channels: email, webhook, dashboard notifications
- Requires: more frequent data ingestion (every 5-15 min from TSO APIs), a baseline model, alert throttling

### Direction C: Scenario Analysis & Backtesting

Enable counterfactual questions about the market.

- "What would prices have been last January if Olkiluoto had been online?"
- "How often does EE price exceed 100 EUR/MWh when wind < 2 GW and Narva is partially offline?"
- "If 500 MW of new LT-PL interconnector capacity is added, what happens to LT price volatility?"
- Requires: deep historical data (2+ years), a simulation or statistical model for counterfactuals

### Direction D: Structured Report Generation

Generate weekly/monthly PDF reports suitable for distribution within a trading organization.

- Professional formatting with charts, tables, and narrative
- Sections: Price Review, Fundamental Drivers, Spread Analysis, Outage Calendar, Weather Outlook
- Backtest mode: generate a report for any historical period and compare predictions vs actuals
- Requires: PDF generation (WeasyPrint or similar), chart rendering (matplotlib/plotly), templating

### Direction E: Dashboard & Visualization ✅ (basic)

- [x] Streamlit dashboard with Plotly charts: hourly prices, generation mix, cross-border flows, wind vs price, price heatmap
- [x] Briefing viewer page with date selector
- [x] CLI command: `uv run python -m grid_signals ui`
- [x] Interconnector flow visualization (map-based)
- [ ] Spread evolution over time chart

### Direction F: Production Hardening (Single Server) ✅

**Critical:**
- [x] CI pipeline (GitHub Actions): ruff linting, mypy type checking, pytest on every push
- [ ] Add authentication to Streamlit (nginx basic auth or built-in password)
- [x] Rate limit chat page to cap daily LLM spend
- [x] Structured logging (JSON format) — stdlib JSONFormatter, auto-detect TTY
- [x] Failure alerting: Prefect automations (configurable via Prefect UI)
- [x] Daily health check: verify all jobs ran, latest `period_start` is within 26h
- [x] Automated daily PostgreSQL backup (pg_dump) to S3 (30-day retention via S3 lifecycle policy)
- [x] Add timeouts to ENTSO-E (60s) and Anthropic (120s) API calls
- [x] Validate environment variables at startup with clear error messages
- [x] Run validation *before* briefing generation so bad data doesn't produce a bad briefing

**Scheduling — migrated from cron to Prefect:**
- [x] Prefect flows and tasks wrapping existing pipeline functions
- [x] Cron-based schedules with catchup for missed runs
- [x] Built-in retries, timeouts, and failure handling per task
- [x] Docker Compose deployment (Prefect server + worker)
- [x] Prefect UI dashboard for observability at localhost:4200

**Code quality:**
- [x] Add ruff and mypy to project dev dependencies and CI
- [x] Add pytest coverage reporting (pytest-cov)

### Direction I: VRE Generation Forecast Models (in progress)

Standalone ML development of probabilistic day-ahead wind and solar generation forecasts, in
`research/` — deliberately **not integrated** with grid-signals; the integration deliverable is a
written contract only. Renewable quantiles are the highest-value input to Direction H.

- Targets: **SE3 onshore wind** first, then **DE-LU solar** (Swedish PV is largely behind-the-meter,
  so ENTSO-E sees only a small metered slice — see `research/docs/dataflow.md`)
- Approach: physics fitted on ERA5, thin statistical correction fitted on matched-lead NWP archives;
  quantile GBM with multi-model spread as the uncertainty signal
- Benchmark: climatology, persistence and a physical power-curve baseline. **ENTSO-E A69 turned out
  not to be a usable day-ahead bar** — it scores 1.77% nMAE against SE3 actuals where published
  day-ahead wind skill is 3–6%, so the served revision postdates gate closure
- [x] Phase 1 — dataflow diagram (`research/docs/dataflow.md`) and project scaffold
- [x] Phase 2 — data audit (`research/reports/data_audit.md`) — GO for SE3 wind
- [x] Phase 3 — targets, frozen protocol (`research/reports/protocol.md`), baselines
- [x] Phase 4 — NWP feature pipeline (`research/reports/openmeteo_vintage.md`)
- [x] Phase 5 — modelling (`research/reports/modelling.md`)
- [x] Phase 6a — MEPS ensemble spike (`research/reports/meps_archive.md`) — conditional GO
- [x] Phase 6c — improvement roadmap (`research/docs/roadmap.md`): run-addressed NWP (MEPS +
  IFS HRES) and cross-fitted, spread-stratified calibration shipped — typical miss 143 → 122 MW,
  80% coverage 0.74 → 0.78
- [ ] Phase 6b — DE-LU solar
- [x] Phase 7a — integration contract (`research/docs/integration_contract.md`)
- [ ] Phase 7b — operational dry-run

### Direction G: Multi-Tenant SaaS

Turn the tool into a product that multiple trading desks can use.

- User/org management, configurable zones and alert thresholds
- Per-user conversation history and preferences
- API access for integration with existing trading systems
- Requires: auth, multi-tenancy, deployment infrastructure, significant additional engineering

### Direction H: Forecast Model

Build a quantitative price forecasting model alongside the LLM agent.

- Feature engineering: wind forecast, temperature, outage MW offline, day-of-week, season, lagged prices, hydro reservoir levels
- Model: gradient-boosted trees (LightGBM) or similar
- The LLM agent can call a `get_price_forecast(zone, date)` tool that returns the model's prediction with confidence intervals
- Compare model forecast vs actual day-ahead price as a quality metric
