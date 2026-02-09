# Grid Signals — Roadmap

Nordic-Baltic Energy Intelligence Agent: automated market analysis powered by structured data and LLM reasoning.

---

## MVP — Data Ingestion + Daily Briefing

The MVP delivers two things: a reliable data pipeline that pulls from public energy/weather APIs into a local database, and an LLM agent that queries that data to produce a daily morning briefing.

### Milestone 1: Project Setup & Data Models

**Goal:** Establish project structure, define schemas, set up DuckDB.

- [ ] Initialize Python project (pyproject.toml, uv/pip, basic directory structure)
- [ ] Define data models / schemas for:
  - Day-ahead prices by bidding zone (EE, LV, LT, FI, SE4, SE3)
  - Generation by fuel type per zone
  - Total load forecast per zone
  - Cross-border physical flows (interconnector capacities and scheduled exchanges)
  - REMIT outage messages (planned and unplanned)
  - Wind speed and solar irradiance forecasts for key locations
- [ ] Set up DuckDB database with tables matching these schemas
- [ ] Write a thin data-access layer (Python functions that query DuckDB and return structured results)

**Key decisions:**
- Bidding zones in scope for MVP: EE, LV, LT, FI, SE4. Possibly SE3 for wind context.
- Time granularity: hourly for prices/generation/load, daily for outages.
- DuckDB for storage — single-file, no server, fast analytical queries, good parquet support.

### Milestone 2: Data Ingestion — ENTSO-E

**Goal:** Pull core market data from the ENTSO-E Transparency Platform.

Data available from ENTSO-E:
- Day-ahead prices (all zones)
- Aggregated generation per type (wind, solar, nuclear, gas, oil shale, hydro, etc.)
- Total load and load forecast
- Cross-border physical flows between bidding zones
- REMIT urgent market messages (outages)
- Scheduled commercial exchanges

Implementation:
- [ ] Register for ENTSO-E API key (free, takes ~3 days for approval)
- [ ] Use `entsoe-py` library as the API wrapper
- [ ] Build ingestion functions for each data type:
  - `ingest_day_ahead_prices(zones, date_range)`
  - `ingest_generation_per_type(zones, date_range)`
  - `ingest_total_load(zones, date_range)`
  - `ingest_cross_border_flows(borders, date_range)`
  - `ingest_outages(zones, date_range)`
- [ ] Handle ENTSO-E API quirks: XML response parsing, rate limiting (400 requests/min), pagination for large date ranges, timezone handling (all data is UTC but markets trade in CET)
- [ ] Write data to DuckDB, with upsert logic to avoid duplicates on re-runs
- [ ] Backfill 3-6 months of historical data for each data type

**Key risks:**
- ENTSO-E API key approval can take several business days.
- The API is unreliable at times — build in retries with exponential backoff.
- Some data types have different availability delays (day-ahead prices available ~13:00 CET D-1, generation actuals available next day).

### Milestone 3: Data Ingestion — Weather (Open-Meteo)

**Goal:** Pull wind and solar forecasts for key generation regions.

- [ ] Identify key coordinates:
  - Southern Sweden (SE4): ~56.0°N, 14.0°E (Skåne wind farms)
  - Central Sweden (SE3): ~59.0°N, 16.0°E
  - Finland: ~61.5°N, 24.0°E (inland wind), ~63.0°N, 21.0°E (Ostrobothnia coast)
  - Estonia: ~59.0°N, 25.0°E
  - Lithuania: ~55.5°N, 24.0°E
- [ ] Use Open-Meteo free API (no key required):
  - Wind speed at 100m hub height
  - Solar irradiance (GHI)
  - Temperature (drives demand)
  - Forecast horizon: 7 days ahead, hourly
- [ ] Build ingestion: `ingest_weather_forecast(locations, date_range)`
- [ ] Store both the forecast and when it was fetched (to track forecast revisions)
- [ ] Backfill historical weather actuals for model context

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
- [ ] Evaluate: Litgrid/AST APIs for LT/LV (less mature, may skip for MVP)

**Note:** Some of this data overlaps with ENTSO-E. The TSO APIs are useful for near-real-time data (updated every few minutes) vs ENTSO-E (hourly/daily).

### Milestone 5: Scheduling & Pipeline Orchestration

**Goal:** Automate data ingestion on a schedule.

- [ ] For MVP, use a simple scheduler — `cron` or a lightweight Python scheduler (APScheduler)
  - Daily at 05:00 EET: pull latest day-ahead prices, generation forecasts, outages
  - Every 6 hours: update weather forecasts
  - Daily: backfill any gaps from previous days
- [ ] Add basic logging and error handling
  - Log each ingestion run (source, date range, rows inserted, errors)
  - Alert on failure (email or log notification)
- [ ] Data validation checks:
  - No missing hours in price data
  - Prices within reasonable bounds (negative OK, but flag if < -500 or > 4000 EUR/MWh)
  - Wind forecasts not stale (check timestamp)

**Decision: Airflow vs simple cron.**
Airflow is overkill for MVP. A cron job calling a Python script is sufficient. Move to Airflow later if the DAG complexity grows.

### Milestone 6: LLM Agent with Tool Use

**Goal:** Build an LLM agent that can query the database through structured tools and reason about the data.

Tools to implement:
- [ ] `get_day_ahead_prices(zone: str, start: date, end: date)` — returns hourly prices
- [ ] `get_generation_mix(zone: str, date: date)` — returns generation by fuel type
- [ ] `get_wind_forecast(region: str, start: date, end: date)` — returns wind speed/generation forecast
- [ ] `get_outages(zone: str, fuel_type: str | None)` — returns active REMIT outage messages
- [ ] `get_cross_border_flows(from_zone: str, to_zone: str, start: date, end: date)` — returns scheduled/actual flows
- [ ] `get_load_forecast(zone: str, start: date, end: date)` — returns total load forecast
- [ ] `calculate_spread(zone_1: str, zone_2: str, start: date, end: date)` — computes price spread time series
- [ ] `get_historical_similar_days(zone: str, conditions: dict)` — finds past days with similar wind/temp/outage patterns and returns their prices

Agent design:
- [ ] Use Claude API with tool use
- [ ] System prompt with domain knowledge:
  - Interconnector capacities (SE4-LT: ~700 MW, FI-EE: ~1000 MW, EE-LV: ~800 MW, LT-PL: ~500 MW)
  - Key generation assets (Olkiluoto 1&2: ~1.7 GW nuclear, Narva oil shale: ~1.1 GW, Kruonis pumped storage: 900 MW)
  - Market coupling mechanics (how day-ahead auction works, price convergence when interconnectors not congested)
  - Seasonal patterns (spring flood drives Nordic hydro, winter demand peaks in Baltics, wind seasonality)
- [ ] Multi-step reasoning: agent should call multiple tools, compare results, and synthesize
- [ ] Grounding: all numbers in the output must come from tool calls, not from the LLM

### Milestone 7: Daily Briefing Generation

**Goal:** Automated morning briefing generated by the LLM agent.

- [ ] Briefing generation script that:
  1. Calls the agent with a structured prompt: "Generate a morning briefing for Baltic-Nordic day-ahead trading"
  2. The agent autonomously decides which tools to call based on what's interesting
  3. Agent produces a structured briefing with sections:
     - **Key signal** — the single most important thing to know today
     - **Price outlook** — day-ahead price expectations with drivers
     - **Wind & weather** — forecast and how it compares to recent days
     - **Outages** — any new or notable REMIT messages
     - **Spreads** — cross-border spread analysis
     - **Watch list** — things to monitor during the day
- [ ] Schedule briefing generation at 06:30 EET (after day-ahead results are published)
- [ ] Output format: structured text (Markdown) saved to file
- [ ] Delivery mechanism to be decided (email, web UI, or other — see post-MVP directions)

### Milestone 8: Testing, Documentation & Polish

- [ ] Integration tests: mock API responses, verify ingestion writes correct data
- [ ] Unit tests for spread calculation, similar-day matching logic
- [ ] End-to-end test: seed DB with known data, run briefing generation, verify output references correct numbers
- [ ] README with:
  - Architecture diagram
  - Setup instructions
  - Example briefing output
  - Screenshots or sample outputs
- [ ] Clean up CLAUDE.md with actual build/test commands

---

## Post-MVP — Future Directions

After the MVP is working and delivering daily briefings, there are several directions to expand. These are not sequential — pick based on interest and feedback.

### Direction A: Interactive Chat Interface

Add a conversational interface so users can ask follow-up questions about the market.

- Web UI (FastAPI + React) with conversation memory
- Persistent conversation context — the agent remembers what was discussed earlier in the session
- Example queries:
  - "What's driving the FI-EE spread today?"
  - "How does tomorrow compare to last Tuesday?"
  - "What happens if Olkiluoto comes back online Thursday?"
- Requires: conversation management, potentially session storage, more robust error handling for open-ended queries

### Direction B: Anomaly Detection & Real-Time Alerts

Shift from scheduled briefings to continuous monitoring with alerts when something unusual happens.

- Build a statistical baseline model: expected price given wind forecast, temperature, outage schedule, day-of-week, season
- Detect significant deviations from the baseline in near-real-time
- LLM explains the anomaly: what's unusual and what might be causing it
- Alert channels: email, webhook, dashboard notifications
- Requires: more frequent data ingestion (every 5-15 min from TSO APIs), a baseline model (could be as simple as quantile regression or a gradient-boosted model), alert throttling to avoid fatigue

### Direction C: Scenario Analysis & Backtesting

Enable counterfactual questions about the market.

- "What would prices have been last January if Olkiluoto had been online?"
- "How often does EE price exceed 100 EUR/MWh when wind < 2 GW and Narva is partially offline?"
- "If 500 MW of new LT-PL interconnector capacity is added, what happens to LT price volatility?"
- Requires: deep historical data (2+ years), a simulation or statistical model for counterfactuals, careful prompt engineering to distinguish "data says" from "model estimates"

### Direction D: Structured Report Generation

Generate weekly/monthly PDF reports suitable for distribution within a trading organization.

- Professional formatting with charts, tables, and narrative
- Sections: Price Review, Fundamental Drivers, Spread Analysis, Outage Calendar, Weather Outlook
- Backtest mode: generate a report for any historical period and compare predictions vs actuals
- Requires: PDF generation (WeasyPrint or similar), chart rendering (matplotlib/plotly exported as images), templating

### Direction E: Dashboard & Visualization

Build a web dashboard with live charts and the briefing.

- Price heatmap across bidding zones (hourly, colored by price level)
- Wind forecast vs actuals chart
- Spread evolution over time
- Interconnector flow visualization (map-based)
- The daily briefing text alongside the charts
- Tech: FastAPI backend serving data + React frontend with a charting library (Recharts, D3, or Plotly)

### Direction F: Multi-Tenant SaaS

Turn the tool into a product that multiple trading desks can use.

- User/org management, configurable zones and alert thresholds
- Per-user conversation history and preferences
- API access for integration with existing trading systems
- Pricing model: monthly subscription per seat
- Requires: auth, multi-tenancy, deployment infrastructure, uptime monitoring, significant additional engineering

### Direction G: Forecast Model

Build a quantitative price forecasting model alongside the LLM agent.

- Feature engineering: wind forecast, temperature, outage MW offline, day-of-week, season, lagged prices, hydro reservoir levels
- Model: gradient-boosted trees (LightGBM) or similar, trained on historical data
- The LLM agent can call a `get_price_forecast(zone, date)` tool that returns the model's prediction with confidence intervals
- Compare model forecast vs actual day-ahead price as a quality metric
- Requires: ML pipeline, feature store, model training and evaluation, monitoring for model drift

---

## Technical Stack (MVP)

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.12+ | Ecosystem for data + LLM |
| Database | DuckDB | Embedded analytical DB, parquet support, no server |
| ENTSO-E client | entsoe-py | Wraps the painful XML API |
| Weather data | Open-Meteo API | Free, no key, good forecast data |
| LLM | Claude API (tool use) | Strong reasoning, native tool use |
| Scheduling | cron + Python scripts | Simple, sufficient for MVP |
| Delivery | TBD (email / web UI) | Decide post-MVP based on user feedback |
| Testing | pytest | Standard |
| Package mgmt | uv | Fast, modern Python package management |

---

## Open Questions

- **ENTSO-E API key:** Need to register and wait for approval. This is a blocker for Milestone 2. Can develop against cached/mock data in the meantime.
- **Fingrid API:** Registration required. Evaluate whether data adds enough value over ENTSO-E alone for MVP.
- **Historical backfill depth:** 3 months is minimal for "similar day" matching. 6-12 months is better but takes longer to ingest (ENTSO-E rate limits).
- **LLM cost:** Claude API calls for daily briefing + occasional chat. Estimate: ~$1-3/day depending on tool call volume. Acceptable for a portfolio project.
- **Delivery channel:** Email, web dashboard, or another push mechanism — decide based on who the early users are and what they prefer.
