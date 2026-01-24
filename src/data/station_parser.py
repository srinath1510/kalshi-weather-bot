"""
NWS Station Observation Parser for Kalshi Weather Bot.

Parses real-time NWS observations with conversion handling for
temperature uncertainty bounds.

Key features:
- Identifies station type (hourly vs 5-minute)
- Handles °C → °F conversion uncertainty
- Calculates possible actual temperature bounds
- Tracks observed high and uncertainty for settlement prediction
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests

from src.interfaces import StationReading, DailyObservation, StationDataSource, StationType
from src.config import (
    NYC,
    NWS_STATIONS_URL,
    NWS_USER_AGENT,
    API_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Uncertainty constants for temperature conversion
# 5-minute stations report Celsius rounded to 0.1°C
# This creates ±0.05°C uncertainty which is ±0.09°F
FIVE_MINUTE_C_PRECISION = 0.1  # °C
FIVE_MINUTE_F_UNCERTAINTY = 0.1  # °F (rounded up from 0.09)

# Hourly stations report more precisely, lower uncertainty
HOURLY_F_UNCERTAINTY = 0.5  # °F

# Additional uncertainty for settlement: actual max could be between readings
# If readings are 5 minutes apart, max could occur between them
INTER_READING_UNCERTAINTY = 1.0  # °F


def celsius_to_fahrenheit(celsius: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0


def calculate_temp_bounds(
    temp_c: Optional[float],
    temp_f: float,
    station_type: StationType,
) -> tuple[float, float]:
    """
    Calculate possible actual temperature bounds given conversion uncertainty.

    Args:
        temp_c: Temperature in Celsius (if available from API)
        temp_f: Temperature in Fahrenheit
        station_type: Type of station (affects uncertainty)

    Returns:
        Tuple of (low_bound_f, high_bound_f) for possible actual temperature
    """
    if station_type == StationType.FIVE_MINUTE:
        # 5-minute stations have more uncertainty due to:
        # 1. Celsius rounding (±0.05°C = ±0.09°F)
        # 2. Potential additional rounding in F display
        uncertainty = FIVE_MINUTE_F_UNCERTAINTY + 0.5  # Total ~0.6°F
    elif station_type == StationType.HOURLY:
        # Hourly stations are more precise
        uncertainty = HOURLY_F_UNCERTAINTY
    else:
        # Unknown station type, use conservative uncertainty
        uncertainty = 1.0

    return (temp_f - uncertainty, temp_f + uncertainty)


def determine_station_type(observations: List[dict]) -> StationType:
    """
    Determine station type based on observation frequency.

    Args:
        observations: List of observation dicts from NWS API

    Returns:
        StationType based on typical interval between observations
    """
    if len(observations) < 2:
        return StationType.UNKNOWN

    # Calculate intervals between consecutive observations
    intervals = []
    for i in range(len(observations) - 1):
        try:
            time1 = observations[i].get("properties", {}).get("timestamp")
            time2 = observations[i + 1].get("properties", {}).get("timestamp")

            if time1 and time2:
                dt1 = datetime.fromisoformat(time1.replace("Z", "+00:00"))
                dt2 = datetime.fromisoformat(time2.replace("Z", "+00:00"))
                interval_minutes = abs((dt1 - dt2).total_seconds() / 60)
                intervals.append(interval_minutes)
        except (ValueError, TypeError):
            continue

    if not intervals:
        return StationType.UNKNOWN

    avg_interval = sum(intervals) / len(intervals)

    # 5-minute stations have ~5 minute intervals
    # Hourly stations have ~60 minute intervals
    if avg_interval < 15:
        return StationType.FIVE_MINUTE
    elif avg_interval >= 45:
        return StationType.HOURLY
    else:
        return StationType.UNKNOWN


def parse_observation(obs: dict, station_type: StationType, station_id: str) -> Optional[StationReading]:
    """
    Parse a single observation from NWS API response.

    Args:
        obs: Observation dict from NWS API
        station_type: Type of station
        station_id: Station identifier

    Returns:
        StationReading or None if parsing fails
    """
    try:
        properties = obs.get("properties", {})

        # Parse timestamp
        timestamp_str = properties.get("timestamp")
        if not timestamp_str:
            return None
        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

        # Parse temperature
        temp_data = properties.get("temperature", {})
        temp_value = temp_data.get("value")
        unit_code = temp_data.get("unitCode", "")

        if temp_value is None:
            return None

        # NWS API typically returns Celsius
        if "degC" in unit_code or "celsius" in unit_code.lower():
            temp_c = float(temp_value)
            temp_f = celsius_to_fahrenheit(temp_c)
        elif "degF" in unit_code or "fahrenheit" in unit_code.lower():
            temp_f = float(temp_value)
            temp_c = None
        else:
            # Assume Celsius if unit not specified
            temp_c = float(temp_value)
            temp_f = celsius_to_fahrenheit(temp_c)

        # Calculate bounds
        low_f, high_f = calculate_temp_bounds(temp_c, temp_f, station_type)

        return StationReading(
            station_id=station_id,
            timestamp=timestamp,
            station_type=station_type,
            reported_temp_f=round(temp_f, 1),
            reported_temp_c=round(temp_c, 1) if temp_c is not None else None,
            possible_actual_f_low=round(low_f, 1),
            possible_actual_f_high=round(high_f, 1),
        )
    except (ValueError, TypeError, KeyError) as e:
        logger.warning(f"Failed to parse observation: {e}")
        return None


class NWSStationParser(StationDataSource):
    """Fetches and parses NWS station observations."""

    def __init__(self, station_id: str, timezone: str = "America/New_York"):
        self.station_id = station_id
        self.timezone = ZoneInfo(timezone)
        self._cached_observations: List[dict] = []
        self._station_type: Optional[StationType] = None
        self._last_fetch: Optional[datetime] = None

    def _get_headers(self) -> dict:
        """Return headers for NWS API requests."""
        return {"User-Agent": NWS_USER_AGENT}

    def _fetch_raw_observations(self, limit: int = 100) -> List[dict]:
        """
        Fetch raw observations from NWS API.

        Args:
            limit: Maximum number of observations to fetch

        Returns:
            List of observation dicts from API
        """
        try:
            url = NWS_STATIONS_URL.format(station_id=self.station_id)
            params = {"limit": limit}

            response = requests.get(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=API_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            features = data.get("features", [])
            self._cached_observations = features
            self._last_fetch = datetime.now(self.timezone)

            # Determine station type from observations
            if features:
                self._station_type = determine_station_type(features)

            return features
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch NWS observations: {e}")
            return []
        except (ValueError, KeyError) as e:
            logger.warning(f"Failed to parse NWS observations response: {e}")
            return []

    def fetch_current_observations(self) -> List[StationReading]:
        """Fetch recent observations from the station."""
        raw_observations = self._fetch_raw_observations()

        if not raw_observations:
            return []

        station_type = self._station_type or StationType.UNKNOWN
        readings = []

        for obs in raw_observations:
            reading = parse_observation(obs, station_type, self.station_id)
            if reading:
                readings.append(reading)

        return readings

    def get_daily_summary(self, date: str) -> Optional[DailyObservation]:
        """
        Get aggregated observation data for a specific date.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            DailyObservation with aggregated data, or None if no data
        """
        readings = self.fetch_current_observations()

        if not readings:
            return None

        # Filter readings for the target date
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        daily_readings = [
            r for r in readings
            if r.timestamp.astimezone(self.timezone).date() == target_date
        ]

        if not daily_readings:
            return None

        # Find the highest reported temperature
        max_reading = max(daily_readings, key=lambda r: r.reported_temp_f)
        observed_high_f = max_reading.reported_temp_f

        # Calculate possible actual high bounds
        # The actual high could be:
        # 1. Higher than any reading due to inter-reading variation
        # 2. Within the uncertainty bounds of the max reading

        # Get the max of all possible_actual_f_high values
        max_possible_high = max(r.possible_actual_f_high for r in daily_readings)

        # Add inter-reading uncertainty (temperature could spike between readings)
        possible_actual_high_high = max_possible_high + INTER_READING_UNCERTAINTY

        # The minimum possible actual high is the observed high minus uncertainty
        # (in case the max reading was at the upper end of its uncertainty)
        possible_actual_high_low = observed_high_f - HOURLY_F_UNCERTAINTY

        return DailyObservation(
            station_id=self.station_id,
            date=date,
            observed_high_f=observed_high_f,
            possible_actual_high_low=round(possible_actual_high_low, 1),
            possible_actual_high_high=round(possible_actual_high_high, 1),
            readings=daily_readings,
            last_updated=datetime.now(self.timezone),
        )

    def get_station_type(self) -> StationType:
        """Get the determined station type."""
        return self._station_type or StationType.UNKNOWN


def get_station_observations(
    station_id: str = "KNYC",
    timezone: str = "America/New_York",
) -> List[StationReading]:
    """
    Convenience function to fetch current observations for a station.

    Args:
        station_id: NWS station identifier (default: KNYC for NYC)
        timezone: Timezone string (default: America/New_York)

    Returns:
        List of StationReading objects
    """
    parser = NWSStationParser(station_id, timezone)
    return parser.fetch_current_observations()


def get_daily_observation(
    date: str,
    station_id: str = "KNYC",
    timezone: str = "America/New_York",
) -> Optional[DailyObservation]:
    """
    Convenience function to get daily observation summary.

    Args:
        date: Date in YYYY-MM-DD format
        station_id: NWS station identifier (default: KNYC for NYC)
        timezone: Timezone string (default: America/New_York)

    Returns:
        DailyObservation or None if no data available
    """
    parser = NWSStationParser(station_id, timezone)
    return parser.get_daily_summary(date)
