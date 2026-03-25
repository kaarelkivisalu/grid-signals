# Nordic-Baltic Electricity Market Changes (2025–)

Significant market, regulatory, and infrastructure changes relevant for grid-signals data pipelines.

---

## 2024-04-17 — REMIT II Published; Rolling Out Through 2025–2026

**Region:** EE, LV, LT, FI, SE1, SE2, SE3, SE4, NO1, NO2, NO3, NO4, NO5, DK1, DK2 (all EU members)

Revised REMIT (Regulation (EU) 2024/1106) broadens reporting obligations to new asset types (battery storage, demand response), tightens insider trading rules, and requires more granular market data reporting. Implementing provisions rolling out through 2025–2026.

**Pipeline impact:**
- New generation asset types (battery storage, demand response aggregators) may appear in `generation_by_type` data.
- Outage reporting tightened — potentially more frequent and granular outage publications in ENTSO-E.
- New fuel/technology type enums may require schema or mapping updates.

**Sources:**
- [Regulation (EU) 2024/1106 — EUR-Lex Official Journal](https://eur-lex.europa.eu/eli/reg/2024/1106/oj/eng)

---

## 2024–2026 — ENTSO-E Transparency Platform Modernization

**Region:** All (platform-level)

ENTSO-E has been modernizing the Transparency Platform, including potential API migration from legacy RESTful XML to JSON/GraphQL, improved data quality monitoring, and new datasets (storage, hydro reservoir fill rates).

**Pipeline impact:**
- API breaking changes could require `entsoe-py` updates or ingestion layer rewrite.
- Rate limiting (currently 400 req/min) may change.
- New data endpoints become available.
- Mitigation: pin `entsoe-py` version, test before upgrading, monitor ENTSO-E release notes.

**Sources:**
- [Electricity Market Transparency — ENTSO-E](https://www.entsoe.eu/data/transparency-platform/)
- [Webinar: Discover the New ENTSO-E Transparency Platform (Oct 2025)](https://www.entsoe.eu/events/2025/10/29/webinar-invitation-discover-the-new-entso-e-transparency-platform/)

---

## 2024-11-04 — Flow-Based Market Coupling (FBMC) Go-Live in the Nordics

**Region:** NO1, NO2, NO3, NO4, NO5, SE1, SE2, SE3, SE4, FI, DK1, DK2

Transition from Available Transfer Capacity (ATC) based coupling to Flow-Based Market Coupling for the day-ahead market. Uses PTDFs and remaining available margins (RAMs) instead of simple NTC/ATC values. Aligns the Nordics with Central Western Europe (FBMC since 2015). Go-live was postponed multiple times before successful implementation in November 2024.

**Pipeline impact:**
- ENTSO-E publishes different data under FBMC: PTDFs, RAMs, critical network elements — `cross_border_flows` table may need schema updates.
- Day-ahead price formation changes: more frequent price convergence between zones when flow-based domain is larger than old ATC values, but also new congestion patterns.
- Structural break in price spreads and cross-border flow correlations from this date.

**Sources:**
- [Flow-Based Methodology Successfully Implemented in the Nordic Region — ENTSO-E press release](https://www.entsoe.eu/documents/nc/NC%20CACM/SDAC%202024/Nordic_FB_PR.pdf)
- [Nordic Flow-Based Day-Ahead Market Coupling — Nord Pool](https://www.nordpoolgroup.com/en/trading/nordic-flow-based-day-ahead-market-coupling/)

---

## 2025-02-08 00:00 UTC — Baltic Synchronization with Continental Europe

**Region:** EE, LV, LT

The three Baltic states disconnected from the IPS/UPS synchronous area (Russia/Belarus) and synchronized with the Continental European synchronous area via the LitPol Link. This was the culmination of a decade-long geopolitical and technical project.

**Pipeline impact:**
- Cross-border flow patterns changed — flows via Estlink 1 & 2 (EE–FI) and NordBalt (LT–SE4) now operate under different synchronous area coupling rules; LT–PL link gained significance as a synchronous AC connection.
- Balancing market shifted from bilateral arrangements with Russia to European balancing platforms, affecting load and generation dispatch data.
- Hard structural break in historical time-series — any analysis spanning before/after must account for fundamentally different grid topology.

**Sources:**
- [ENTSO-E confirms successful synchronization of the Continental European electricity system with the Baltic countries (2025-02-09)](https://www.entsoe.eu/news/2025/02/09/entso-e-confirms-successful-synchronization-of-the-continental-european-electricity-system-with-the-systems-of-the-baltic-countries/)
- [Estonian, Latvian, and Lithuanian power systems successfully synchronised with Continental Europe — Elering](https://elering.ee/en/article/estonian-latvian-and-lithuanian-power-systems-successfully-synchronised-continental-europe)

---

## 2025-06-01 00:00 CET — 15-Minute Imbalance Settlement Period (ISP)

**Region:** EE, LV, LT, FI, SE1, SE2, SE3, SE4, NO1, NO2, NO3, NO4, NO5, DK1, DK2 (EU-wide mandate)

EU Regulation 2019/943 mandated transition from 60-minute to 15-minute imbalance settlement periods. Intraday and balancing markets moved to 15-minute products. Some zones also began publishing 15-minute day-ahead data.

**Pipeline impact:**
- Mixed resolution data: some zones hourly, some 15-min. Already handled via dynamic resolution detection in validation.
- 4× more data points (96 intervals/day instead of 24).
- ENTSO-E Transparency Platform serves data at whatever resolution the zone provides; `entsoe-py` passes it through.

**Sources:**
- [Regulation (EU) 2019/943 on the internal market for electricity — EUR-Lex (consolidated 2024)](https://eur-lex.europa.eu/eli/reg/2019/943/2024-07-16/eng)

---

## 2025–2026 (decision pending) — Nordic Bidding Zone Review

**Region:** SE1, SE2, SE3, SE4 (primary); NO1, NO2, NO3, NO4, NO5 (secondary)

Under EU Regulation 2019/943, ACER evaluates whether current bidding zones adequately reflect structural congestion. Sweden's four-zone configuration is under review. Sweden's government has pushed back, but the process is EU-driven.

**Pipeline impact:**
- If zones are split or merged, ENTSO-E zone codes change — `zones` configuration, agent system prompt, and all zone-dependent queries would need updating.
- Historical data continuity breaks at any zone boundary change.
- Slow-moving process; no imminent change expected but warrants monitoring.

**Sources:**
- [Bidding Zone Review — ACER project page](https://www.acer.europa.eu/electricity/market-rules/capacity-allocation-and-congestion-management/bidding-zone-review)
- [ACER has decided on alternative electricity bidding zone configurations — ACER news](https://www.acer.europa.eu/news-and-events/news/acer-has-decided-alternative-electricity-bidding-zone-configurations)

---

## 2025–2026 — Capacity Mechanisms and Strategic Reserve Changes

**Region:** FI (strategic reserve), SE1–SE4 (planned capacity mechanism), EE, LV, LT

Finland operates a strategic reserve for peak demand. Sweden has been discussing a capacity mechanism. Post-synchronization Baltic states need adequate reserve capacity without Russian system support.

**Pipeline impact:**
- Generation-by-type data may show new categories related to reserve activation.
- Outage scheduling patterns may shift as reserve obligations constrain planned maintenance windows.

**Sources:**
- [Peak load capacity 2025 — Fingrid](https://www.fingrid.fi/en/grid/peak-load-capacity/fees/peak-load-capacity-2025/)
- [Reserve power plants — Fingrid](https://www.fingrid.fi/en/electricity-market/reserves_and_balancing/reserve-power-plants/)

---

## Ongoing — Olkiluoto 3 Operational Maturation

**Region:** FI (with price effects across EE, LV, LT)

OL3 (~1.6 GW EPR) reached commercial operation in April 2023 but experienced recurring unplanned outages through 2024–2025. Its operational status is one of the single biggest drivers of FI and Baltic electricity prices.

**Pipeline impact:**
- FI REMIT outage data is critical for capturing OL3 status — must always be up to date.
- OL3 outages immediately tighten Nordic supply-demand balance; the briefing agent should distinguish OL3 (~1.6 GW) from OL1/OL2 (~890 MW combined) since they operate independently.

**Sources:**
- [Regular electricity production has started at Olkiluoto 3 EPR — TVO press release (2023-04-16)](https://www.tvo.fi/en/index/news/pressreleasesstockexchangereleases/2023/regularelectricityproductionhasstartedatolkiluoto3epr.html)
- [OL3 plant unit — TVO](https://www.tvo.fi/en/index/production/plantunits/ol3.html)

---

*Last updated: 2026-03-25. Verify current status of bidding zone decisions through ENTSO-E, Nord Pool, or respective TSO websites.*
