"""
Tests for the probability engine.

Module 2A: Forecast Combiner
Module 2B: Observation Adjuster
"""

import pytest
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from kalshi_weather.core import TemperatureForecast, DailyObservation, StationReading, StationType
from kalshi_weather.engine.probability import (
    # Module 2A
    ForecastCombiner,
    CombinedForecast,
    combine_forecasts,
    DEFAULT_WEIGHTS,
    MIN_STD_DEV,
    MAX_STD_DEV,
    # Module 2B
    ObservationAdjuster,
    AdjustedForecast,
    adjust_forecast_with_observations,
    EARLY_CUTOFF_HOURS,
    LATE_CUTOFF_HOURS,
)


# =============================================================================
# TEST DATA HELPERS
# =============================================================================

TARGET_DATE = "2026-01-20"


def make_forecast(
    source: str,
    temp_f: float,
    std_dev: float = 2.0,
    target_date: str = TARGET_DATE,
) -> TemperatureForecast:
    """Create a test forecast with sensible defaults."""
    return TemperatureForecast(
        source=source,
        target_date=target_date,
        forecast_temp_f=temp_f,
        low_f=temp_f - 1.28 * std_dev,
        high_f=temp_f + 1.28 * std_dev,
        std_dev=std_dev,
        model_run_time=None,
        fetched_at=datetime.now(),
    )


# =============================================================================
# WEIGHT LOOKUP TESTS
# =============================================================================


class TestGetWeight:
    """Tests for weight lookup functionality."""

    def test_exact_match(self):
        combiner = ForecastCombiner()
        assert combiner.get_weight("NWS") == 5.0
        assert combiner.get_weight("GFS+HRRR") == 3.0

    def test_partial_match(self):
        combiner = ForecastCombiner()
        # "GFS" should match the GFS weight
        assert combiner.get_weight("GFS") == 2.5

    def test_case_insensitive_match(self):
        combiner = ForecastCombiner()
        # Should find NWS even with different case
        assert combiner.get_weight("nws") == 5.0

    def test_unknown_source_gets_default(self):
        combiner = ForecastCombiner()
        assert combiner.get_weight("SomeUnknownModel") == 1.0

    def test_custom_weights(self):
        custom = {"MyModel": 10.0, "default": 0.5}
        combiner = ForecastCombiner(weights=custom)
        assert combiner.get_weight("MyModel") == 10.0
        assert combiner.get_weight("Unknown") == 0.5


# =============================================================================
# WEIGHTED MEAN TESTS
# =============================================================================


class TestWeightedMean:
    """Tests for weighted mean calculation."""

    def test_single_forecast(self):
        forecasts = [make_forecast("NWS", 55.0)]
        result = combine_forecasts(forecasts)
        assert result is not None
        assert result.mean_temp_f == 55.0

    def test_equal_weight_forecasts(self):
        # Two forecasts with same weight should average
        forecasts = [
            make_forecast("ModelA", 50.0),
            make_forecast("ModelB", 60.0),
        ]
        combiner = ForecastCombiner(weights={"ModelA": 1.0, "ModelB": 1.0, "default": 1.0})
        result = combiner.combine(forecasts)
        assert result is not None
        assert abs(result.mean_temp_f - 55.0) < 0.01

    def test_weighted_mean_favors_higher_weight(self):
        # NWS (weight 5) at 60°F, Unknown (weight 1) at 50°F
        # Weighted mean = (5*60 + 1*50) / 6 = 350/6 ≈ 58.33
        forecasts = [
            make_forecast("NWS", 60.0),
            make_forecast("Unknown", 50.0),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        assert result.mean_temp_f > 55.0  # Should be closer to NWS
        expected = (5 * 60 + 1 * 50) / 6
        assert abs(result.mean_temp_f - expected) < 0.01

    def test_three_forecasts(self):
        # NWS=5, ECMWF=4, GFS=2.5
        forecasts = [
            make_forecast("NWS", 50.0),
            make_forecast("ECMWF", 52.0),
            make_forecast("GFS", 54.0),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        # Weighted mean = (5*50 + 4*52 + 2.5*54) / 11.5 = 593/11.5 ≈ 51.57
        expected = (5 * 50 + 4 * 52 + 2.5 * 54) / 11.5
        assert abs(result.mean_temp_f - expected) < 0.01


# =============================================================================
# UNCERTAINTY COMBINATION TESTS
# =============================================================================


class TestUncertaintyCombination:
    """Tests for combined uncertainty calculation."""

    def test_single_forecast_preserves_std_dev(self):
        forecasts = [make_forecast("NWS", 55.0, std_dev=3.0)]
        result = combine_forecasts(forecasts)
        assert result is not None
        # Single forecast, no disagreement, std_dev should be preserved
        # (but may be clamped to min)
        assert result.std_dev >= MIN_STD_DEV
        assert abs(result.std_dev - 3.0) < 0.01

    def test_agreeing_forecasts_low_uncertainty(self):
        # All forecasts agree on 55°F
        forecasts = [
            make_forecast("NWS", 55.0, std_dev=2.0),
            make_forecast("ECMWF", 55.0, std_dev=2.0),
            make_forecast("GFS", 55.0, std_dev=2.0),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        # No disagreement, so combined std is just pooled individual std
        assert result.std_dev == 2.0

    def test_disagreeing_forecasts_higher_uncertainty(self):
        # Forecasts disagree significantly
        forecasts = [
            make_forecast("NWS", 50.0, std_dev=2.0),
            make_forecast("ECMWF", 60.0, std_dev=2.0),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        # Should have higher uncertainty due to disagreement
        assert result.std_dev > 2.0

    def test_std_dev_minimum_floor(self):
        # Even with very low uncertainty forecasts
        forecasts = [
            make_forecast("NWS", 55.0, std_dev=0.5),
            make_forecast("ECMWF", 55.0, std_dev=0.5),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        assert result.std_dev >= MIN_STD_DEV

    def test_std_dev_maximum_cap(self):
        # Wildly disagreeing forecasts
        forecasts = [
            make_forecast("NWS", 30.0, std_dev=5.0),
            make_forecast("Unknown", 70.0, std_dev=5.0),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        assert result.std_dev <= MAX_STD_DEV

    def test_custom_min_std_dev(self):
        combiner = ForecastCombiner(min_std_dev=3.0)
        forecasts = [make_forecast("NWS", 55.0, std_dev=1.0)]
        result = combiner.combine(forecasts)
        assert result is not None
        assert result.std_dev >= 3.0


# =============================================================================
# PERCENTILE TESTS
# =============================================================================


class TestPercentiles:
    """Tests for low/high percentile calculation."""

    def test_percentiles_symmetric(self):
        forecasts = [make_forecast("NWS", 55.0, std_dev=2.0)]
        result = combine_forecasts(forecasts)
        assert result is not None
        # 10th and 90th percentiles should be symmetric around mean
        assert abs((result.mean_temp_f - result.low_f) - (result.high_f - result.mean_temp_f)) < 0.01

    def test_percentiles_use_z_score(self):
        forecasts = [make_forecast("NWS", 55.0, std_dev=2.0)]
        result = combine_forecasts(forecasts)
        assert result is not None
        # Z-score for 10th/90th percentile is ~1.28
        expected_spread = 1.28155 * 2.0
        assert abs(result.high_f - result.low_f - 2 * expected_spread) < 0.1

    def test_wider_std_gives_wider_range(self):
        narrow = combine_forecasts([make_forecast("NWS", 55.0, std_dev=1.5)])
        wide = combine_forecasts([make_forecast("NWS", 55.0, std_dev=4.0)])
        assert narrow is not None and wide is not None
        narrow_range = narrow.high_f - narrow.low_f
        wide_range = wide.high_f - wide.low_f
        assert wide_range > narrow_range


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_list_returns_none(self):
        result = combine_forecasts([])
        assert result is None

    def test_nan_temperature_filtered(self):
        forecasts = [
            make_forecast("NWS", 55.0),
            make_forecast("Bad", float('nan')),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        assert result.source_count == 1
        assert result.mean_temp_f == 55.0

    def test_all_invalid_returns_none(self):
        forecasts = [
            make_forecast("Bad1", float('nan')),
            make_forecast("Bad2", float('nan')),
        ]
        result = combine_forecasts(forecasts)
        assert result is None

    def test_different_dates_uses_first(self):
        forecasts = [
            make_forecast("NWS", 55.0, target_date="2026-01-20"),
            make_forecast("ECMWF", 56.0, target_date="2026-01-21"),  # Different date
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        assert result.target_date == "2026-01-20"


# =============================================================================
# COMBINED FORECAST PROPERTIES
# =============================================================================


class TestCombinedForecastProperties:
    """Tests for CombinedForecast data class."""

    def test_variance_property(self):
        forecasts = [make_forecast("NWS", 55.0, std_dev=2.0)]
        result = combine_forecasts(forecasts)
        assert result is not None
        assert abs(result.variance - 4.0) < 0.01  # 2.0^2 = 4.0

    def test_sources_used_populated(self):
        forecasts = [
            make_forecast("NWS", 55.0),
            make_forecast("ECMWF", 56.0),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        assert "NWS" in result.sources_used
        assert "ECMWF" in result.sources_used

    def test_weights_used_normalized(self):
        forecasts = [
            make_forecast("NWS", 55.0),
            make_forecast("ECMWF", 56.0),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        # Weights should sum to 1.0
        total = sum(result.weights_used.values())
        assert abs(total - 1.0) < 0.001

    def test_individual_forecasts_stored(self):
        forecasts = [
            make_forecast("NWS", 55.0),
            make_forecast("ECMWF", 56.0),
        ]
        result = combine_forecasts(forecasts)
        assert result is not None
        assert len(result.individual_forecasts) == 2

    def test_combined_at_timestamp(self):
        before = datetime.now()
        result = combine_forecasts([make_forecast("NWS", 55.0)])
        after = datetime.now()
        assert result is not None
        assert before <= result.combined_at <= after


# =============================================================================
# CUSTOM WEIGHTS TESTS
# =============================================================================


class TestCustomWeights:
    """Tests for custom weight functionality."""

    def test_combine_with_custom_weights(self):
        forecasts = [
            make_forecast("ModelA", 50.0),
            make_forecast("ModelB", 60.0),
        ]
        combiner = ForecastCombiner()

        # Custom weights: ModelB has much higher weight
        custom = {"ModelA": 1.0, "ModelB": 9.0, "default": 1.0}
        result = combiner.combine_with_custom_weights(forecasts, custom)

        assert result is not None
        # Weighted mean = (1*50 + 9*60) / 10 = 59
        assert abs(result.mean_temp_f - 59.0) < 0.01

    def test_custom_weights_doesnt_modify_original(self):
        combiner = ForecastCombiner()
        original_nws_weight = combiner.get_weight("NWS")

        forecasts = [make_forecast("NWS", 55.0)]
        custom = {"NWS": 100.0, "default": 1.0}
        combiner.combine_with_custom_weights(forecasts, custom)

        # Original weights should be unchanged
        assert combiner.get_weight("NWS") == original_nws_weight


# =============================================================================
# INTEGRATION-STYLE TESTS
# =============================================================================


class TestRealWorldScenarios:
    """Tests simulating real-world forecast combinations."""

    def test_typical_four_source_combination(self):
        """Simulate combining Open-Meteo Best Match, GFS+HRRR, Ensemble, and NWS."""
        forecasts = [
            make_forecast("Open-Meteo Best Match", 52.0, std_dev=2.0),
            make_forecast("GFS+HRRR", 51.0, std_dev=2.5),
            make_forecast("Open-Meteo Ensemble", 54.0, std_dev=3.0),
            make_forecast("NWS", 50.0, std_dev=2.0),
        ]
        result = combine_forecasts(forecasts)

        assert result is not None
        assert result.source_count == 4
        # NWS should have highest weight, pulling mean toward 50
        assert result.mean_temp_f < 52.5  # Below simple average
        # Uncertainty should account for 4°F spread in forecasts
        assert result.std_dev > 2.0

    def test_high_agreement_scenario(self):
        """All models agree closely - should have lower uncertainty."""
        forecasts = [
            make_forecast("NWS", 55.0, std_dev=2.0),
            make_forecast("ECMWF", 55.5, std_dev=2.0),
            make_forecast("GFS+HRRR", 54.5, std_dev=2.0),
        ]
        result = combine_forecasts(forecasts)

        assert result is not None
        # Mean should be very close to 55
        assert abs(result.mean_temp_f - 55.0) < 0.5
        # Low disagreement should not inflate uncertainty much
        assert result.std_dev < 2.5

    def test_high_disagreement_scenario(self):
        """Models disagree significantly - should have higher uncertainty."""
        forecasts = [
            make_forecast("NWS", 45.0, std_dev=2.0),
            make_forecast("ECMWF", 55.0, std_dev=2.0),
            make_forecast("GFS+HRRR", 50.0, std_dev=2.0),
        ]
        result = combine_forecasts(forecasts)

        assert result is not None
        # 10°F spread between NWS and ECMWF should inflate uncertainty
        assert result.std_dev > 3.0

    def test_single_nws_forecast(self):
        """Only NWS available - should use NWS values directly."""
        forecasts = [make_forecast("NWS", 53.0, std_dev=2.5)]
        result = combine_forecasts(forecasts)

        assert result is not None
        assert result.mean_temp_f == 53.0
        assert result.std_dev == 2.5
        assert result.weights_used["NWS"] == 1.0


# =============================================================================
# MATHEMATICAL CORRECTNESS TESTS
# =============================================================================


class TestMathematicalCorrectness:
    """Tests to verify the mathematical formulas are correct."""

    def test_variance_formula_pooled_component(self):
        """Verify pooled variance is weighted average of individual variances."""
        forecasts = [
            make_forecast("ModelA", 50.0, std_dev=2.0),
            make_forecast("ModelB", 50.0, std_dev=4.0),  # Same temp, different uncertainty
        ]
        combiner = ForecastCombiner(weights={"ModelA": 1.0, "ModelB": 1.0, "default": 1.0})
        result = combiner.combine(forecasts)

        assert result is not None
        # No disagreement (same temp), so variance is just pooled
        # Pooled variance = (1*4 + 1*16) / 2 = 10
        # Std dev = sqrt(10) ≈ 3.16
        expected_std = math.sqrt((4 + 16) / 2)
        assert abs(result.std_dev - expected_std) < 0.01

    def test_variance_formula_disagreement_component(self):
        """Verify disagreement variance is weighted variance of means."""
        forecasts = [
            make_forecast("ModelA", 50.0, std_dev=0.0),
            make_forecast("ModelB", 60.0, std_dev=0.0),  # No individual uncertainty
        ]
        combiner = ForecastCombiner(weights={"ModelA": 1.0, "ModelB": 1.0, "default": 1.0}, min_std_dev=0.0)
        result = combiner.combine(forecasts)

        assert result is not None
        # Mean = 55, disagreement variance = (1*(50-55)^2 + 1*(60-55)^2) / 2 = 25
        # Std dev = sqrt(25) = 5
        assert abs(result.std_dev - 5.0) < 0.01

    def test_variance_formula_combined(self):
        """Verify total variance is sum of pooled and disagreement."""
        forecasts = [
            make_forecast("ModelA", 50.0, std_dev=3.0),
            make_forecast("ModelB", 56.0, std_dev=3.0),
        ]
        combiner = ForecastCombiner(weights={"ModelA": 1.0, "ModelB": 1.0, "default": 1.0}, min_std_dev=0.0)
        result = combiner.combine(forecasts)

        assert result is not None
        # Mean = 53
        # Pooled variance = (9 + 9) / 2 = 9
        # Disagreement variance = ((50-53)^2 + (56-53)^2) / 2 = (9 + 9) / 2 = 9
        # Total variance = 9 + 9 = 18
        # Std dev = sqrt(18) ≈ 4.24
        expected_std = math.sqrt(18)
        assert abs(result.std_dev - expected_std) < 0.01


# =============================================================================
# MODULE 2B: OBSERVATION ADJUSTER TESTS
# =============================================================================

NYC_TZ = ZoneInfo("America/New_York")


def make_combined_forecast(
    mean: float = 55.0,
    std_dev: float = 2.0,
    target_date: str = TARGET_DATE,
) -> CombinedForecast:
    """Create a test combined forecast."""
    z_10 = 1.28155
    return CombinedForecast(
        target_date=target_date,
        mean_temp_f=mean,
        std_dev=std_dev,
        low_f=mean - z_10 * std_dev,
        high_f=mean + z_10 * std_dev,
        source_count=1,
        sources_used=["NWS"],
        weights_used={"NWS": 1.0},
    )


def make_observation(
    observed_high: float = 54.0,
    low_bound: float = 53.0,
    high_bound: float = 55.0,
    date: str = TARGET_DATE,
) -> DailyObservation:
    """Create a test daily observation."""
    reading = StationReading(
        station_id="KNYC",
        timestamp=datetime.now(NYC_TZ),
        station_type=StationType.FIVE_MINUTE,
        reported_temp_f=observed_high,
        reported_temp_c=None,
        possible_actual_f_low=low_bound,
        possible_actual_f_high=high_bound,
    )
    return DailyObservation(
        station_id="KNYC",
        date=date,
        observed_high_f=observed_high,
        possible_actual_high_low=low_bound,
        possible_actual_high_high=high_bound,
        readings=[reading],
        last_updated=datetime.now(NYC_TZ),
    )


def make_time(hour: int, minute: int = 0) -> datetime:
    """Create a datetime at specific hour in NYC timezone."""
    return datetime(2026, 1, 20, hour, minute, tzinfo=NYC_TZ)


# =============================================================================
# TIME-BASED WEIGHT TESTS
# =============================================================================


class TestObservationWeight:
    """Tests for time-based observation weight calculation."""

    def test_before_noon_zero_weight(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        # 10 AM - should be pure forecast
        hours = adjuster._calculate_hours_since_noon(make_time(10, 0))
        weight = adjuster._calculate_observation_weight(hours)
        assert weight == 0.0

    def test_at_noon_zero_weight(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        hours = adjuster._calculate_hours_since_noon(make_time(12, 0))
        weight = adjuster._calculate_observation_weight(hours)
        assert weight == 0.0

    def test_at_1pm_low_weight(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        hours = adjuster._calculate_hours_since_noon(make_time(13, 0))
        weight = adjuster._calculate_observation_weight(hours)
        assert 0.1 < weight < 0.2  # Should be around 0.15

    def test_at_2pm_transitional_weight(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        hours = adjuster._calculate_hours_since_noon(make_time(14, 0))
        weight = adjuster._calculate_observation_weight(hours)
        assert abs(weight - 0.3) < 0.05

    def test_at_3pm_mid_weight(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        hours = adjuster._calculate_hours_since_noon(make_time(15, 0))
        weight = adjuster._calculate_observation_weight(hours)
        assert 0.5 < weight < 0.6

    def test_at_4pm_high_weight(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        hours = adjuster._calculate_hours_since_noon(make_time(16, 0))
        weight = adjuster._calculate_observation_weight(hours)
        assert abs(weight - 0.8) < 0.05

    def test_at_6pm_very_high_weight(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        hours = adjuster._calculate_hours_since_noon(make_time(18, 0))
        weight = adjuster._calculate_observation_weight(hours)
        assert weight > 0.85

    def test_late_evening_approaches_max(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        hours = adjuster._calculate_hours_since_noon(make_time(20, 0))
        weight = adjuster._calculate_observation_weight(hours)
        assert weight >= 0.9
        assert weight <= 0.95  # Never reaches 1.0

    def test_weight_monotonically_increases(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        weights = []
        for hour in range(12, 21):
            hours = adjuster._calculate_hours_since_noon(make_time(hour, 0))
            weights.append(adjuster._calculate_observation_weight(hours))
        # Each weight should be >= previous
        for i in range(1, len(weights)):
            assert weights[i] >= weights[i - 1]


# =============================================================================
# ADJUSTED MEAN TESTS
# =============================================================================


class TestAdjustedMean:
    """Tests for adjusted mean calculation."""

    def test_no_observation_unchanged(self):
        forecast = make_combined_forecast(mean=55.0)
        result = adjust_forecast_with_observations(forecast, None)
        assert result.mean_temp_f == 55.0
        assert result.observation_weight == 0.0

    def test_early_morning_mostly_forecast(self):
        forecast = make_combined_forecast(mean=55.0)
        observation = make_observation(observed_high=50.0)
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(10, 0)
        )
        # Before noon, should be pure forecast
        assert result.mean_temp_f == 55.0

    def test_late_day_mostly_observation(self):
        forecast = make_combined_forecast(mean=55.0)
        observation = make_observation(observed_high=58.0)
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(18, 0)
        )
        # Late day, should be much closer to observation
        assert result.mean_temp_f > 56.5

    def test_mean_never_below_observed_high(self):
        forecast = make_combined_forecast(mean=50.0)
        observation = make_observation(observed_high=55.0)
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(15, 0)
        )
        # Mean can't be below what we've observed
        assert result.mean_temp_f >= 55.0

    def test_blending_at_midday(self):
        forecast = make_combined_forecast(mean=60.0)
        observation = make_observation(observed_high=50.0)
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(15, 0)
        )
        # Should be between forecast and observation, but >= observed
        assert result.mean_temp_f >= 50.0
        assert result.mean_temp_f < 60.0


# =============================================================================
# ADJUSTED UNCERTAINTY TESTS
# =============================================================================


class TestAdjustedUncertainty:
    """Tests for adjusted standard deviation calculation."""

    def test_no_observation_preserves_std(self):
        forecast = make_combined_forecast(mean=55.0, std_dev=3.0)
        result = adjust_forecast_with_observations(forecast, None)
        assert result.std_dev == 3.0

    def test_late_day_reduced_uncertainty(self):
        forecast = make_combined_forecast(mean=55.0, std_dev=3.0)
        observation = make_observation(
            observed_high=54.0, low_bound=53.5, high_bound=54.5
        )
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(18, 0)
        )
        # Late day with tight observation bounds should reduce uncertainty
        assert result.std_dev < 3.0

    def test_std_dev_minimum_floor(self):
        forecast = make_combined_forecast(mean=55.0, std_dev=0.5)
        observation = make_observation(
            observed_high=55.0, low_bound=54.9, high_bound=55.1
        )
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(20, 0)
        )
        # Should still have minimum uncertainty
        assert result.std_dev >= MIN_STD_DEV


# =============================================================================
# CONSTRAINT TESTS
# =============================================================================


class TestConstraints:
    """Tests for min/max possible high constraints."""

    def test_min_possible_from_observation(self):
        forecast = make_combined_forecast(mean=55.0)
        observation = make_observation(low_bound=52.0)
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(15, 0)
        )
        assert result.min_possible_high == 52.0

    def test_low_f_constrained_by_observation(self):
        forecast = make_combined_forecast(mean=55.0, std_dev=5.0)
        observation = make_observation(low_bound=53.0)
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(15, 0)
        )
        # low_f should not go below observation bounds
        assert result.low_f >= 53.0


# =============================================================================
# ADJUSTED FORECAST PROPERTIES
# =============================================================================


class TestAdjustedForecastProperties:
    """Tests for AdjustedForecast data class properties."""

    def test_variance_property(self):
        forecast = make_combined_forecast(mean=55.0, std_dev=2.0)
        result = adjust_forecast_with_observations(forecast, None)
        assert abs(result.variance - 4.0) < 0.01

    def test_is_observation_dominant_false_early(self):
        forecast = make_combined_forecast()
        observation = make_observation()
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(13, 0)
        )
        assert not result.is_observation_dominant

    def test_is_observation_dominant_true_late(self):
        forecast = make_combined_forecast()
        observation = make_observation()
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(17, 0)
        )
        assert result.is_observation_dominant

    def test_stores_original_forecast(self):
        forecast = make_combined_forecast(mean=55.0)
        observation = make_observation()
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(15, 0)
        )
        assert result.original_forecast.mean_temp_f == 55.0

    def test_stores_observation(self):
        forecast = make_combined_forecast()
        observation = make_observation(observed_high=54.0)
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(15, 0)
        )
        assert result.observation is not None
        assert result.observed_high_f == 54.0

    def test_hours_since_noon_recorded(self):
        forecast = make_combined_forecast()
        observation = make_observation()
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(14, 30)
        )
        assert abs(result.hours_since_noon - 2.5) < 0.01


# =============================================================================
# EDGE CASES
# =============================================================================


class TestObservationAdjusterEdgeCases:
    """Tests for edge cases in observation adjustment."""

    def test_empty_readings_treated_as_no_observation(self):
        forecast = make_combined_forecast(mean=55.0)
        observation = DailyObservation(
            station_id="KNYC",
            date=TARGET_DATE,
            observed_high_f=50.0,
            possible_actual_high_low=49.0,
            possible_actual_high_high=51.0,
            readings=[],  # Empty readings
        )
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(15, 0)
        )
        # Should behave as if no observation
        assert result.observation_weight == 0.0
        assert result.mean_temp_f == 55.0

    def test_different_timezone(self):
        la_tz = ZoneInfo("America/Los_Angeles")
        adjuster = ObservationAdjuster(timezone=la_tz)
        # 3 PM LA time
        la_time = datetime(2026, 1, 20, 15, 0, tzinfo=la_tz)
        hours = adjuster._calculate_hours_since_noon(la_time)
        assert abs(hours - 3.0) < 0.01

    def test_naive_datetime_assumes_local(self):
        adjuster = ObservationAdjuster(timezone=NYC_TZ)
        naive_time = datetime(2026, 1, 20, 14, 0)  # No timezone
        hours = adjuster._calculate_hours_since_noon(naive_time)
        assert abs(hours - 2.0) < 0.01


# =============================================================================
# REAL WORLD SCENARIOS
# =============================================================================


class TestObservationAdjusterScenarios:
    """Tests simulating real-world observation adjustment scenarios."""

    def test_morning_cold_observation(self):
        """Morning: observed high is low, forecast expects warmer - trust forecast."""
        forecast = make_combined_forecast(mean=55.0, std_dev=2.0)
        observation = make_observation(observed_high=45.0)
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(9, 0)
        )
        # Morning: pure forecast
        assert result.mean_temp_f == 55.0
        assert result.observation_weight == 0.0

    def test_afternoon_warm_observation(self):
        """Afternoon: observed high exceeds forecast - adjust upward."""
        forecast = make_combined_forecast(mean=55.0, std_dev=2.0)
        observation = make_observation(observed_high=60.0, high_bound=61.0)
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(15, 0)
        )
        # Should be pulled toward observation
        assert result.mean_temp_f >= 60.0  # Can't be below observed

    def test_evening_observation_dominates(self):
        """Evening: observed high should dominate."""
        forecast = make_combined_forecast(mean=50.0, std_dev=2.0)
        observation = make_observation(
            observed_high=55.0, low_bound=54.5, high_bound=55.5
        )
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(19, 0)
        )
        # Evening: close to observation
        assert result.mean_temp_f >= 54.5
        assert result.observation_weight > 0.85

    def test_forecast_observation_agree(self):
        """When forecast and observation agree, uncertainty should be lower."""
        forecast = make_combined_forecast(mean=55.0, std_dev=3.0)
        observation = make_observation(
            observed_high=55.0, low_bound=54.5, high_bound=55.5
        )
        result = adjust_forecast_with_observations(
            forecast, observation, current_time=make_time(15, 0)
        )
        # Agreement should reduce uncertainty somewhat
        assert result.std_dev <= 3.0
