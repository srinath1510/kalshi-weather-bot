"""
Tests for the probability engine - Module 2A: Forecast Combiner.
"""

import pytest
import math
from datetime import datetime

from kalshi_weather.core import TemperatureForecast
from kalshi_weather.engine.probability import (
    ForecastCombiner,
    CombinedForecast,
    combine_forecasts,
    DEFAULT_WEIGHTS,
    MIN_STD_DEV,
    MAX_STD_DEV,
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
