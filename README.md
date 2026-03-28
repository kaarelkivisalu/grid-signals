# Grid Signals

Nordic-Baltic Energy Intelligence Agent. Automated market analysis powered by structured data pipelines and LLM reasoning with tool use.

## Architecture

```
                         ┌──────────────┐
                         │   CLI / Cron │
                         └──────┬───────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
     ┌────────────────┐ ┌─────────────┐  ┌────────────────┐
     │ Data Ingestion │ │   Briefing  │  │   Agent Chat   │
     │                │ │  Generator  │  │                │
     │ - ENTSO-E API  │ │             │  │ "What drove    │
     │ - Open-Meteo   │ │  Structured │  │  EE prices?"   │
     │ - Validation   │ │  prompt →   │  │                │
     └───────┬────────┘ │  Agent →    │  └───────┬────────┘
             │          │  Markdown   │          │
             │          └──────┬──────┘          │
             │                 │                 │
             ▼                 ▼                 ▼
        ┌──────────────────────────────────────────┐
        │              LLM Agent                   │
        │  Claude API with 8 energy market tools   │
        └─────────────────┬────────────────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │   DuckDB    │
                   │             │
                   │ prices      │
                   │ generation  │
                   │ load        │
                   │ flows       │
                   │ outages     │
                   │ weather     │
                   └─────────────┘
```

**Data sources:** ENTSO-E Transparency Platform (prices, generation, load, flows, outages) and Open-Meteo (wind, solar, temperature forecasts).

**Agent tools:** `get_day_ahead_prices`, `get_generation_mix`, `get_wind_forecast`, `get_outages`, `get_cross_border_flows`, `get_load_forecast`, `calculate_spread`, `get_historical_similar_days`.

## Setup

```bash
# Clone and install
git clone <repo-url>
cd grid-signals
uv sync --all-extras

# Set API keys
export ENTSOE_API_KEY="your-key"       # Register at transparency.entsoe.eu
export ANTHROPIC_API_KEY="your-key"    # For the LLM agent
```

## Usage

### Data ingestion

```bash
# Pull yesterday/today/tomorrow data from ENTSO-E
uv run grid-signals daily

# Update weather forecasts (7-day ahead)
uv run grid-signals weather

# Backfill a specific date range
uv run grid-signals backfill --start 2024-01-01 --end 2024-03-31

# Run data validation checks
uv run grid-signals validate
```

### Morning briefing

```bash
# Generate today's briefing (saved to briefings/YYYY-MM-DD.md)
uv run grid-signals briefing

# Generate for a specific date
uv run grid-signals briefing --date 2024-03-15

# Custom output directory
uv run grid-signals briefing --output reports/
```

### Interactive agent

```bash
# Ask a question
uv run grid-signals agent "What are the key drivers for EE prices today?"

# Use a specific model
uv run grid-signals agent "Compare FI and EE spreads this week" --model claude-sonnet-4-20250514
```

### Scheduling

Install the example crontab for automated daily operation:

```bash
# Review and edit paths first
vi crontab.example
crontab crontab.example
```

This schedules:

- **05:00 EET** — daily data ingestion
- **Every 6h** — weather forecast updates
- **05:30 EET** — gap backfill (last 3 days)
- **05:45 EET** — data validation
- **06:30 EET** — morning briefing generation

## Example briefing output

```markdown
## Key Signal

Finnish nuclear capacity remains constrained with Olkiluoto 2 (890 MW)
offline until March 20, keeping FI prices elevated and driving imports
via EstLink.

## Price Outlook

Estonian day-ahead prices averaged 73.00 EUR/MWh, ranging from 50.00 to
96.00 EUR/MWh. Finnish prices averaged 63.00 EUR/MWh, with FI
consistently cheaper than EE by 10.00 EUR/MWh.

## Wind & Weather

Wind speeds at EE_tallinn held steady at 8.5 m/s throughout the day,
above typical March averages. Solar irradiance at 120 W/m2 with
temperatures around 2.0°C.

## Outages

Olkiluoto 2 (FI, nuclear, 890 MW) — planned outage through March 20.
No new outage messages.

## Spreads

EE-FI spread was a constant 10.00 EUR/MWh (EE more expensive),
indicating persistent EstLink congestion. FI→EE flows at 500 MW near
interconnector capacity.

## Watch List

- Olkiluoto 2 return on March 20 — watch for schedule changes
- Wind forecast evolution for SE4 and FI regions
- EE-FI spread narrowing if FI wind picks up
```

## Testing

```bash
uv run pytest tests/
```

## Tech stack

| Component      | Choice                |
| -------------- | --------------------- |
| Language       | Python 3.12+          |
| Database       | DuckDB                |
| ENTSO-E client | entsoe-py             |
| Weather data   | Open-Meteo API        |
| LLM            | Claude API (tool use) |
| Scheduling     | cron                  |
| Testing        | pytest                |
| Package mgmt   | uv                    |
