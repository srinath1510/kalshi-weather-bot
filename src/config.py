"""
Configuration constants for Kalshi Weather Bot.

Contains API endpoints, coordinates, and trading parameters.
"""

from dataclasses import dataclass


# =============================================================================
# CITY CONFIGURATION
# =============================================================================

@dataclass(frozen=True)
class CityConfig:
    """Configuration for a supported city."""
    name: str              # Full city name
    code: str              # Short code (e.g., "NYC")
    station_id: str        # NWS station ID (e.g., "KNYC")
    lat: float             # Latitude
    lon: float             # Longitude
    series_ticker: str     # Kalshi series ticker
    timezone: str          # Timezone string


# NYC Configuration (Primary focus)
NYC = CityConfig(
    name="New York City",
    code="NYC",
    station_id="KNYC",
    lat=40.7829,
    lon=-73.9654,
    series_ticker="KXHIGHNY",
    timezone="America/New_York"
)

# Default city
DEFAULT_CITY = NYC


# =============================================================================
# API ENDPOINTS
# =============================================================================

# Open-Meteo APIs (free, no auth required)
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GFS_URL = "https://api.open-meteo.com/v1/gfs"
OPEN_METEO_ENSEMBLE_URL = "https://api.open-meteo.com/v1/ensemble"

# NWS APIs (free, no auth required)
NWS_API_BASE = "https://api.weather.gov"
NWS_STATIONS_URL = "https://api.weather.gov/stations/{station_id}/observations"

# NWS Climate Report (settlement source)
NWS_CLIMATE_URL = "https://www.weather.gov/wrh/climate"
NWS_CLIMATE_WFO = "okx"  # Weather Forecast Office for NYC

# Kalshi API (public endpoints, no auth for market data)
KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_MARKETS_URL = f"{KALSHI_API_BASE}/markets"


# =============================================================================
# API SETTINGS
# =============================================================================

API_TIMEOUT = 10  # seconds
NWS_USER_AGENT = "KalshiWeatherBot/1.0 (github.com/kalshi-weather-bot)"
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds


# =============================================================================
# TRADING PARAMETERS
# =============================================================================

MIN_EDGE_THRESHOLD = 0.08  # 8% minimum edge to signal
MAX_EDGE_THRESHOLD = 0.40  # 40% - above this, data might be stale
KALSHI_FEE_RATE = 0.10     # 10% fee on winnings


# =============================================================================
# FORECAST PARAMETERS
# =============================================================================

# Minimum standard deviation floor (prevent overconfidence)
MIN_STD_DEV = 1.5  # °F

# Default std dev when not provided by model
DEFAULT_STD_DEV = 2.5  # °F


# =============================================================================
# DISPLAY SETTINGS
# =============================================================================

DEFAULT_REFRESH_INTERVAL = 60  # seconds
