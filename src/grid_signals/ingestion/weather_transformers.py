"""Pure functions: Open-Meteo JSON → WeatherForecast Pydantic models."""

from datetime import UTC, datetime

from grid_signals.ingestion.locations import WeatherLocation
from grid_signals.models.weather import WeatherForecast


def transform_weather_response(
    data: dict, location: WeatherLocation, fetched_at: datetime
) -> list[WeatherForecast]:
    """Convert an Open-Meteo hourly JSON response to WeatherForecast models.

    Works for both forecast and archive API responses (same structure).
    Skips hours where all three variables are None.
    """
    hourly = data["hourly"]
    times = hourly["time"]
    winds = hourly["wind_speed_100m"]
    irradiances = hourly["shortwave_radiation"]
    temps = hourly["temperature_2m"]

    rows: list[WeatherForecast] = []
    for i, iso_str in enumerate(times):
        wind = winds[i]
        irr = irradiances[i]
        temp = temps[i]
        if wind is None and irr is None and temp is None:
            continue
        rows.append(
            WeatherForecast(
                location_name=location.name,
                latitude=location.latitude,
                longitude=location.longitude,
                timestamp=datetime.fromisoformat(iso_str).replace(tzinfo=UTC),
                fetched_at=fetched_at,
                wind_speed_100m_ms=wind,
                solar_irradiance_wm2=irr,
                temperature_c=temp,
            )
        )
    return rows
