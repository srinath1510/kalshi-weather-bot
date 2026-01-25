"""Data fetching modules for weather forecasts, observations, and markets."""

from kalshi_weather.data.weather import (
    OpenMeteoSource,
    NWSForecastSource,
    CombinedWeatherSource,
    fetch_all_forecasts,
)

from kalshi_weather.data.stations import (
    NWSStationParser,
    get_station_observations,
    get_daily_observation,
    celsius_to_fahrenheit,
    calculate_temp_bounds,
    determine_station_type,
)

from kalshi_weather.data.markets import (
    KalshiMarketClient,
    fetch_brackets_for_date,
    get_market_summary,
    parse_bracket_subtitle,
    calculate_implied_probability,
    format_date_for_ticker,
)

__all__ = [
    # Weather
    "OpenMeteoSource",
    "NWSForecastSource",
    "CombinedWeatherSource",
    "fetch_all_forecasts",
    # Stations
    "NWSStationParser",
    "get_station_observations",
    "get_daily_observation",
    "celsius_to_fahrenheit",
    "calculate_temp_bounds",
    "determine_station_type",
    # Markets
    "KalshiMarketClient",
    "fetch_brackets_for_date",
    "get_market_summary",
    "parse_bracket_subtitle",
    "calculate_implied_probability",
    "format_date_for_ticker",
]
