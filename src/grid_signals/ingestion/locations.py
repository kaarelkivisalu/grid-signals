"""Weather forecast locations for the Nordic-Baltic region."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WeatherLocation:
    """A named geographic point for weather data retrieval."""

    name: str
    latitude: float
    longitude: float


# Key wind/solar generation regions per bidding zone.
LOCATIONS: list[WeatherLocation] = [
    WeatherLocation("SE4_skane", 56.0, 14.0),
    WeatherLocation("SE3_central", 59.0, 16.0),
    WeatherLocation("FI_inland", 61.5, 24.0),
    WeatherLocation("FI_ostrobothnia", 63.0, 21.0),
    WeatherLocation("EE_tallinn", 59.0, 25.0),
    WeatherLocation("LT_kaunas", 55.5, 24.0),
    WeatherLocation("LV_riga", 57.0, 24.0),
    WeatherLocation("NO1_oslo", 59.9, 10.7),
    WeatherLocation("NO2_kristiansand", 58.1, 8.0),
    WeatherLocation("NO3_trondheim", 63.4, 10.4),
    WeatherLocation("NO4_tromso", 69.6, 19.0),
    WeatherLocation("NO5_bergen", 60.4, 5.3),
    WeatherLocation("DK1_jutland", 56.0, 8.5),
    WeatherLocation("DK2_zealand", 55.7, 12.0),
]
