"""
Tests for NWS station observation parser module.

Uses the `responses` library to mock HTTP requests.
"""

import pytest
import responses
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.data.station_parser import (
    NWSStationParser,
    get_station_observations,
    get_daily_observation,
    celsius_to_fahrenheit,
    calculate_temp_bounds,
    determine_station_type,
    parse_observation,
    FIVE_MINUTE_F_UNCERTAINTY,
    HOURLY_F_UNCERTAINTY,
    INTER_READING_UNCERTAINTY,
)
from src.interfaces import StationType
from src.config import NWS_STATIONS_URL, NYC


# =============================================================================
# TEST DATA
# =============================================================================

STATION_ID = "KNYC"
TARGET_DATE = "2026-01-20"
BASE_URL = NWS_STATIONS_URL.format(station_id=STATION_ID)

# Timezone for NYC
NYC_TZ = ZoneInfo("America/New_York")


def make_observation(
    timestamp: str,
    temp_c: float,
    unit_code: str = "wmoUnit:degC",
) -> dict:
    """Create a mock NWS observation dict."""
    return {
        "type": "Feature",
        "properties": {
            "timestamp": timestamp,
            "temperature": {
                "value": temp_c,
                "unitCode": unit_code,
            },
        },
    }


def make_api_response(observations: list) -> dict:
    """Create a mock NWS API response."""
    return {
        "@context": [],
        "type": "FeatureCollection",
        "features": observations,
    }


# Sample observations for 5-minute station (5-min intervals)
FIVE_MINUTE_OBSERVATIONS = [
    make_observation("2026-01-20T17:00:00+00:00", 11.1),  # 52.0°F
    make_observation("2026-01-20T16:55:00+00:00", 11.7),  # 53.1°F
    make_observation("2026-01-20T16:50:00+00:00", 12.2),  # 54.0°F - MAX
    make_observation("2026-01-20T16:45:00+00:00", 11.9),  # 53.4°F
    make_observation("2026-01-20T16:40:00+00:00", 11.5),  # 52.7°F
]

# Sample observations for hourly station (60-min intervals)
HOURLY_OBSERVATIONS = [
    make_observation("2026-01-20T17:00:00+00:00", 11.1),  # 52.0°F
    make_observation("2026-01-20T16:00:00+00:00", 12.2),  # 54.0°F - MAX
    make_observation("2026-01-20T15:00:00+00:00", 10.0),  # 50.0°F
    make_observation("2026-01-20T14:00:00+00:00", 8.9),   # 48.0°F
]


# =============================================================================
# UNIT CONVERSION TESTS
# =============================================================================


class TestCelsiusToFahrenheit:
    """Tests for celsius_to_fahrenheit function."""

    def test_freezing_point(self):
        """Test 0°C = 32°F."""
        assert celsius_to_fahrenheit(0) == 32.0

    def test_boiling_point(self):
        """Test 100°C = 212°F."""
        assert celsius_to_fahrenheit(100) == 212.0

    def test_typical_temperature(self):
        """Test typical outdoor temperature."""
        # 20°C = 68°F
        assert abs(celsius_to_fahrenheit(20) - 68.0) < 0.01

    def test_negative_temperature(self):
        """Test negative Celsius."""
        # -10°C = 14°F
        assert abs(celsius_to_fahrenheit(-10) - 14.0) < 0.01

    def test_decimal_precision(self):
        """Test decimal precision in conversion."""
        # 12.5°C should convert accurately
        result = celsius_to_fahrenheit(12.5)
        expected = 12.5 * 9 / 5 + 32  # 54.5°F
        assert abs(result - expected) < 0.001


# =============================================================================
# TEMPERATURE BOUNDS TESTS
# =============================================================================


class TestCalculateTempBounds:
    """Tests for calculate_temp_bounds function."""

    def test_five_minute_station_bounds(self):
        """Test bounds for 5-minute station are wider."""
        low, high = calculate_temp_bounds(12.0, 53.6, StationType.FIVE_MINUTE)

        # 5-minute stations have more uncertainty
        uncertainty = FIVE_MINUTE_F_UNCERTAINTY + 0.5
        assert abs(low - (53.6 - uncertainty)) < 0.01
        assert abs(high - (53.6 + uncertainty)) < 0.01

    def test_hourly_station_bounds(self):
        """Test bounds for hourly station are tighter."""
        low, high = calculate_temp_bounds(12.0, 53.6, StationType.HOURLY)

        assert abs(low - (53.6 - HOURLY_F_UNCERTAINTY)) < 0.01
        assert abs(high - (53.6 + HOURLY_F_UNCERTAINTY)) < 0.01

    def test_unknown_station_conservative(self):
        """Test unknown station type uses conservative bounds."""
        low, high = calculate_temp_bounds(12.0, 53.6, StationType.UNKNOWN)

        # Should use 1.0°F uncertainty for unknown
        assert abs(low - 52.6) < 0.01
        assert abs(high - 54.6) < 0.01

    def test_bounds_without_celsius(self):
        """Test bounds calculation when Celsius is not available."""
        low, high = calculate_temp_bounds(None, 54.0, StationType.HOURLY)

        assert low < 54.0
        assert high > 54.0


# =============================================================================
# STATION TYPE DETECTION TESTS
# =============================================================================


class TestDetermineStationType:
    """Tests for determine_station_type function."""

    def test_five_minute_detection(self):
        """Test detection of 5-minute station."""
        station_type = determine_station_type(FIVE_MINUTE_OBSERVATIONS)
        assert station_type == StationType.FIVE_MINUTE

    def test_hourly_detection(self):
        """Test detection of hourly station."""
        station_type = determine_station_type(HOURLY_OBSERVATIONS)
        assert station_type == StationType.HOURLY

    def test_single_observation(self):
        """Test with only one observation returns unknown."""
        single = [FIVE_MINUTE_OBSERVATIONS[0]]
        station_type = determine_station_type(single)
        assert station_type == StationType.UNKNOWN

    def test_empty_observations(self):
        """Test with no observations returns unknown."""
        station_type = determine_station_type([])
        assert station_type == StationType.UNKNOWN

    def test_mixed_intervals(self):
        """Test with mixed intervals between hourly and 5-minute."""
        # 30-minute intervals should return UNKNOWN
        mixed = [
            make_observation("2026-01-20T17:00:00+00:00", 11.0),
            make_observation("2026-01-20T16:30:00+00:00", 12.0),
            make_observation("2026-01-20T16:00:00+00:00", 11.5),
        ]
        station_type = determine_station_type(mixed)
        assert station_type == StationType.UNKNOWN


# =============================================================================
# OBSERVATION PARSING TESTS
# =============================================================================


class TestParseObservation:
    """Tests for parse_observation function."""

    def test_parse_celsius_observation(self):
        """Test parsing observation with Celsius temperature."""
        obs = make_observation("2026-01-20T15:00:00+00:00", 12.5)
        reading = parse_observation(obs, StationType.HOURLY, STATION_ID)

        assert reading is not None
        assert reading.station_id == STATION_ID
        assert reading.station_type == StationType.HOURLY
        assert reading.reported_temp_c == 12.5
        # 12.5°C = 54.5°F
        assert abs(reading.reported_temp_f - 54.5) < 0.1

    def test_parse_fahrenheit_observation(self):
        """Test parsing observation with Fahrenheit temperature."""
        obs = make_observation("2026-01-20T15:00:00+00:00", 54.5, "wmoUnit:degF")
        reading = parse_observation(obs, StationType.HOURLY, STATION_ID)

        assert reading is not None
        assert reading.reported_temp_f == 54.5
        assert reading.reported_temp_c is None

    def test_parse_missing_temperature(self):
        """Test parsing observation with missing temperature returns None."""
        obs = {
            "type": "Feature",
            "properties": {
                "timestamp": "2026-01-20T15:00:00+00:00",
                "temperature": {"value": None, "unitCode": "wmoUnit:degC"},
            },
        }
        reading = parse_observation(obs, StationType.HOURLY, STATION_ID)
        assert reading is None

    def test_parse_missing_timestamp(self):
        """Test parsing observation with missing timestamp returns None."""
        obs = {
            "type": "Feature",
            "properties": {
                "temperature": {"value": 12.0, "unitCode": "wmoUnit:degC"},
            },
        }
        reading = parse_observation(obs, StationType.HOURLY, STATION_ID)
        assert reading is None

    def test_parse_includes_bounds(self):
        """Test that parsed observation includes uncertainty bounds."""
        obs = make_observation("2026-01-20T15:00:00+00:00", 12.5)
        reading = parse_observation(obs, StationType.FIVE_MINUTE, STATION_ID)

        assert reading is not None
        assert reading.possible_actual_f_low < reading.reported_temp_f
        assert reading.possible_actual_f_high > reading.reported_temp_f


# =============================================================================
# NWS STATION PARSER TESTS
# =============================================================================


class TestNWSStationParser:
    """Tests for NWSStationParser class."""

    @responses.activate
    def test_fetch_current_observations_success(self):
        """Test successful fetch of current observations."""
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(FIVE_MINUTE_OBSERVATIONS),
            status=200,
        )

        parser = NWSStationParser(STATION_ID)
        readings = parser.fetch_current_observations()

        assert len(readings) == 5
        assert all(r.station_id == STATION_ID for r in readings)

    @responses.activate
    def test_fetch_detects_station_type(self):
        """Test that fetching also detects station type."""
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(FIVE_MINUTE_OBSERVATIONS),
            status=200,
        )

        parser = NWSStationParser(STATION_ID)
        parser.fetch_current_observations()

        assert parser.get_station_type() == StationType.FIVE_MINUTE

    @responses.activate
    def test_fetch_api_error(self):
        """Test handling of API error."""
        responses.add(
            responses.GET,
            BASE_URL,
            status=500,
        )

        parser = NWSStationParser(STATION_ID)
        readings = parser.fetch_current_observations()

        assert readings == []

    @responses.activate
    def test_fetch_timeout(self):
        """Test handling of request timeout."""
        from requests.exceptions import Timeout

        responses.add(
            responses.GET,
            BASE_URL,
            body=Timeout("Connection timed out"),
        )

        parser = NWSStationParser(STATION_ID)
        readings = parser.fetch_current_observations()

        assert readings == []

    @responses.activate
    def test_get_daily_summary_success(self):
        """Test getting daily summary for a specific date."""
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(FIVE_MINUTE_OBSERVATIONS),
            status=200,
        )

        parser = NWSStationParser(STATION_ID, "UTC")
        summary = parser.get_daily_summary(TARGET_DATE)

        assert summary is not None
        assert summary.station_id == STATION_ID
        assert summary.date == TARGET_DATE
        # Max temp should be ~54°F (from 12.2°C observation)
        assert abs(summary.observed_high_f - 54.0) < 0.5

    @responses.activate
    def test_get_daily_summary_no_data(self):
        """Test getting daily summary when no observations exist."""
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response([]),
            status=200,
        )

        parser = NWSStationParser(STATION_ID)
        summary = parser.get_daily_summary(TARGET_DATE)

        assert summary is None

    @responses.activate
    def test_get_daily_summary_wrong_date(self):
        """Test getting daily summary for date with no readings."""
        # Observations are for 2026-01-20, but we request 2026-01-21
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(FIVE_MINUTE_OBSERVATIONS),
            status=200,
        )

        parser = NWSStationParser(STATION_ID, "UTC")
        summary = parser.get_daily_summary("2026-01-21")

        assert summary is None

    @responses.activate
    def test_daily_summary_includes_uncertainty_bounds(self):
        """Test that daily summary includes proper uncertainty bounds."""
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(FIVE_MINUTE_OBSERVATIONS),
            status=200,
        )

        parser = NWSStationParser(STATION_ID, "UTC")
        summary = parser.get_daily_summary(TARGET_DATE)

        assert summary is not None
        # Possible high should be higher than observed (inter-reading uncertainty)
        assert summary.possible_actual_high_high > summary.observed_high_f
        # Possible low should be lower than observed (measurement uncertainty)
        assert summary.possible_actual_high_low < summary.observed_high_f


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module convenience functions."""

    @responses.activate
    def test_get_station_observations(self):
        """Test get_station_observations convenience function."""
        url = NWS_STATIONS_URL.format(station_id="KNYC")
        responses.add(
            responses.GET,
            url,
            json=make_api_response(FIVE_MINUTE_OBSERVATIONS),
            status=200,
        )

        readings = get_station_observations("KNYC")

        assert len(readings) == 5

    @responses.activate
    def test_get_daily_observation(self):
        """Test get_daily_observation convenience function."""
        url = NWS_STATIONS_URL.format(station_id="KNYC")
        responses.add(
            responses.GET,
            url,
            json=make_api_response(FIVE_MINUTE_OBSERVATIONS),
            status=200,
        )

        summary = get_daily_observation(TARGET_DATE, "KNYC", "UTC")

        assert summary is not None
        assert summary.date == TARGET_DATE


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @responses.activate
    def test_malformed_observation_skipped(self):
        """Test that malformed observations are skipped without crashing."""
        observations = [
            make_observation("2026-01-20T17:00:00+00:00", 11.1),
            {"type": "Feature", "properties": {}},  # Missing temp
            make_observation("2026-01-20T16:50:00+00:00", 12.2),
        ]
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(observations),
            status=200,
        )

        parser = NWSStationParser(STATION_ID)
        readings = parser.fetch_current_observations()

        # Should only get 2 valid readings
        assert len(readings) == 2

    @responses.activate
    def test_negative_temperatures(self):
        """Test handling of negative temperatures."""
        observations = [
            make_observation("2026-01-20T17:00:00+00:00", -5.0),  # -5°C = 23°F
            make_observation("2026-01-20T16:55:00+00:00", -10.0),  # -10°C = 14°F
        ]
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(observations),
            status=200,
        )

        parser = NWSStationParser(STATION_ID, "UTC")
        summary = parser.get_daily_summary(TARGET_DATE)

        assert summary is not None
        # Max should be 23°F (-5°C)
        assert abs(summary.observed_high_f - 23.0) < 0.5

    @responses.activate
    def test_readings_list_populated(self):
        """Test that daily summary includes the readings list."""
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(FIVE_MINUTE_OBSERVATIONS),
            status=200,
        )

        parser = NWSStationParser(STATION_ID, "UTC")
        summary = parser.get_daily_summary(TARGET_DATE)

        assert summary is not None
        assert len(summary.readings) == 5
        assert all(r.station_id == STATION_ID for r in summary.readings)

    def test_invalid_json_response(self):
        """Test handling of invalid JSON response."""
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                BASE_URL,
                body="not valid json",
                status=200,
            )

            parser = NWSStationParser(STATION_ID)
            readings = parser.fetch_current_observations()

            assert readings == []


# =============================================================================
# UNCERTAINTY CALCULATION TESTS
# =============================================================================


class TestUncertaintyCalculations:
    """Tests for temperature uncertainty calculations."""

    @responses.activate
    def test_inter_reading_uncertainty_applied(self):
        """Test that inter-reading uncertainty is applied to high bound."""
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(FIVE_MINUTE_OBSERVATIONS),
            status=200,
        )

        parser = NWSStationParser(STATION_ID, "UTC")
        summary = parser.get_daily_summary(TARGET_DATE)

        assert summary is not None
        # The possible_actual_high_high should include INTER_READING_UNCERTAINTY
        # Max observation is ~54°F, so high bound should be higher
        assert summary.possible_actual_high_high >= summary.observed_high_f + 0.5

    @responses.activate
    def test_hourly_station_tighter_bounds(self):
        """Test that hourly stations have tighter uncertainty bounds."""
        responses.add(
            responses.GET,
            BASE_URL,
            json=make_api_response(HOURLY_OBSERVATIONS),
            status=200,
        )

        parser = NWSStationParser(STATION_ID, "UTC")
        readings = parser.fetch_current_observations()

        # Hourly stations should have StationType.HOURLY
        assert parser.get_station_type() == StationType.HOURLY

        # Check that readings have appropriate bounds
        for reading in readings:
            spread = reading.possible_actual_f_high - reading.possible_actual_f_low
            # Hourly stations should have smaller spread
            assert spread <= 2 * (HOURLY_F_UNCERTAINTY + 0.1)
