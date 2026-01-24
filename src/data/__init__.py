"""Data fetching modules for weather forecasts and observations."""

from src.data.weather_models import (
    OpenMeteoSource,
    NWSForecastSource,
    CombinedWeatherSource,
    fetch_all_forecasts,
)

from src.data.station_parser import (
    NWSStationParser,
    get_station_observations,
    get_daily_observation,
    celsius_to_fahrenheit,
    calculate_temp_bounds,
    determine_station_type,
)

__all__ = [
    # Weather models
    "OpenMeteoSource",
    "NWSForecastSource",
    "CombinedWeatherSource",
    "fetch_all_forecasts",
    # Station parser
    "NWSStationParser",
    "get_station_observations",
    "get_daily_observation",
    "celsius_to_fahrenheit",
    "calculate_temp_bounds",
    "determine_station_type",
]
