"""European bidding-zone coverage, separate from the operational database enum.

Membership reviewed against ENTSO-E SDAC scope on 2026-10-15. Positions are
illustrative label anchors, not bidding-zone boundaries. Data availability is
reported by the exported manifest, never inferred from membership.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Market:
    code: str
    name: str
    lat: float
    lon: float
    timezone: str = "Europe/Berlin"
    sdac: bool = True


MARKETS = [
    Market("DE_LU", "Germany-Luxembourg", 51.0, 10.4),
    Market("SE3", "Sweden · Central", 59.2, 15.5, "Europe/Stockholm"),
    Market("SE1", "Sweden · North", 67.2, 21.1, "Europe/Stockholm"),
    Market("SE2", "Sweden · North-central", 63.2, 17.8, "Europe/Stockholm"),
    Market("SE4", "Sweden · South", 56.1, 14.0, "Europe/Stockholm"),
    Market("FI", "Finland", 64.0, 26.0, "Europe/Helsinki"),
    Market("EE", "Estonia", 58.8, 25.5, "Europe/Tallinn"),
    Market("LV", "Latvia", 56.9, 24.6, "Europe/Riga"),
    Market("LT", "Lithuania", 55.3, 23.8, "Europe/Vilnius"),
    Market("DK1", "Denmark · West", 56.2, 9.0, "Europe/Copenhagen"),
    Market("DK2", "Denmark · East", 55.6, 12.0, "Europe/Copenhagen"),
    Market("NO1", "Norway · Southeast", 60.2, 10.5, "Europe/Oslo"),
    Market("NO2", "Norway · Southwest", 58.7, 6.5, "Europe/Oslo"),
    Market("NO3", "Norway · Central", 63.2, 10.3, "Europe/Oslo"),
    Market("NO4", "Norway · North", 68.0, 16.1, "Europe/Oslo"),
    Market("NO5", "Norway · West", 61.0, 6.0, "Europe/Oslo"),
    Market("FR", "France", 46.6, 2.5, "Europe/Paris"),
    Market("NL", "Netherlands", 52.2, 5.4, "Europe/Amsterdam"),
    Market("BE", "Belgium", 50.6, 4.5, "Europe/Brussels"),
    Market("AT", "Austria", 47.6, 14.1, "Europe/Vienna"),
    Market("PL", "Poland", 52.0, 19.1, "Europe/Warsaw"),
    Market("CZ", "Czechia", 49.8, 15.5, "Europe/Prague"),
    Market("SK", "Slovakia", 48.7, 19.5, "Europe/Bratislava"),
    Market("HU", "Hungary", 47.1, 19.5, "Europe/Budapest"),
    Market("SI", "Slovenia", 46.1, 14.9, "Europe/Ljubljana"),
    Market("HR", "Croatia", 45.3, 16.3, "Europe/Zagreb"),
    Market("RO", "Romania", 45.8, 24.9, "Europe/Bucharest"),
    Market("BG", "Bulgaria", 42.8, 25.5, "Europe/Sofia"),
    Market("GR", "Greece", 39.2, 22.5, "Europe/Athens"),
    Market("ES", "Spain", 40.0, -3.6, "Europe/Madrid"),
    Market("PT", "Portugal", 39.7, -8.1, "Europe/Lisbon"),
    Market("IT_NORD", "Italy · North", 45.3, 10.0, "Europe/Rome"),
    Market("IT_CNOR", "Italy · Centre-north", 43.6, 11.2, "Europe/Rome"),
    Market("IT_CSUD", "Italy · Centre-south", 41.8, 13.1, "Europe/Rome"),
    Market("IT_SUD", "Italy · South", 40.5, 16.3, "Europe/Rome"),
    Market("IT_CALA", "Italy · Calabria", 39.0, 16.4, "Europe/Rome"),
    Market("IT_SICI", "Italy · Sicily", 37.6, 14.1, "Europe/Rome"),
    Market("IT_SARD", "Italy · Sardinia", 40.1, 9.0, "Europe/Rome"),
    Market("IE_SEM", "Ireland / Northern Ireland · SEM", 53.5, -7.7, "Europe/Dublin"),
    Market("GB", "Great Britain", 54.0, -2.3, "Europe/London", sdac=False),
    Market("CH", "Switzerland", 46.8, 8.2, "Europe/Zurich", sdac=False),
    Market("RS", "Serbia", 44.0, 20.8, "Europe/Belgrade", sdac=False),
    Market("BA", "Bosnia and Herzegovina", 44.1, 17.7, sdac=False),
    Market("ME", "Montenegro", 42.7, 19.1, sdac=False),
    Market("AL", "Albania", 41.1, 20.0, sdac=False),
    Market("MK", "North Macedonia", 41.6, 21.7, sdac=False),
    Market("XK", "Kosovo", 42.6, 21.0, sdac=False),
    Market("TR", "Türkiye", 39.8, 32.6, "Europe/Istanbul", sdac=False),
    Market("UA", "Ukraine", 49.0, 31.0, "Europe/Kyiv", sdac=False),
    Market("MD", "Moldova", 47.2, 28.6, "Europe/Chisinau", sdac=False),
    Market("CY", "Cyprus", 35.0, 33.1, "Asia/Nicosia", sdac=False),
    Market("MT", "Malta", 35.9, 14.4, "Europe/Malta", sdac=False),
    Market("IS", "Iceland", 64.8, -18.5, "Atlantic/Reykjavik", sdac=False),
]
BY_CODE = {market.code: market for market in MARKETS}
TARGETS = {
    "price": "Spot price",
    "load": "Total load",
    "solar": "Solar",
    "wind_onshore": "Onshore wind",
    "residual_load": "Residual load",
}
SELECTED_MODELS = {
    "price": "lear_hourly",
    "load": "load_quantile_gbm",
    "solar": "solar_quantile",
    "wind_onshore": "hourly_repeated",
}
SDAC_SOURCE = "https://www.entsoe.eu/network_codes/cacm/implementation/sdac/"
