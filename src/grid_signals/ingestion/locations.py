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
    WeatherLocation("EE", 59.0, 25.0),
    WeatherLocation("LT", 55.5, 24.0),
    WeatherLocation("LV", 57.0, 24.0),
]
