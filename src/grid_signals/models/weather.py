from datetime import datetime

from pydantic import BaseModel


class WeatherForecast(BaseModel):
    """Hourly weather forecast for a specific location."""

    location_name: str  # e.g. "SE4_skane", "FI_ostrobothnia"
    latitude: float
    longitude: float
    timestamp: datetime  # UTC, forecast valid time
    fetched_at: datetime  # UTC, when this forecast was retrieved
    wind_speed_100m_ms: float | None  # m/s at 100m hub height
    solar_irradiance_wm2: float | None  # GHI in W/m²
    temperature_c: float | None
