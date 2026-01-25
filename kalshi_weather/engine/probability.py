"""
Forecast Combiner

Combines multiple weather forecasts into a single probability distribution
using weighted averaging and proper uncertainty propagation.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from kalshi_weather.core import TemperatureForecast

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Default weights by source (higher = more trusted)
# These are relative weights, will be normalized during combination
DEFAULT_WEIGHTS: Dict[str, float] = {
    # NWS is the settlement source, highest weight
    "NWS": 5.0,
    # ECMWF is generally considered the best global model
    "ECMWF": 4.0,
    # Open-Meteo Best Match blends multiple models intelligently
    "Open-Meteo Best Match": 3.5,
    # GFS+HRRR combination - good for short-term US forecasts
    "GFS+HRRR": 3.0,
    "GFS": 2.5,
    "HRRR": 2.5,
    # Ensemble provides uncertainty info but individual mean less reliable
    "Open-Meteo Ensemble": 2.0,
    # Generic fallback for unknown sources
    "default": 1.0,
}

# Minimum standard deviation floor (in Fahrenheit)
# Even the best forecasts have at least this much uncertainty
MIN_STD_DEV: float = 1.5

# Maximum standard deviation cap (sanity check)
MAX_STD_DEV: float = 10.0


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class CombinedForecast:
    """
    Result of combining multiple forecasts into a single distribution.

    Represents the final probability distribution for temperature,
    modeled as a normal distribution with mean and std_dev.
    """
    target_date: str                    # YYYY-MM-DD format
    mean_temp_f: float                  # Combined weighted mean temperature
    std_dev: float                      # Combined uncertainty (std deviation)
    low_f: float                        # 10th percentile estimate
    high_f: float                       # 90th percentile estimate
    source_count: int                   # Number of forecasts combined
    sources_used: List[str]             # Names of sources included
    weights_used: Dict[str, float]      # Normalized weights applied
    individual_forecasts: List[TemperatureForecast] = field(default_factory=list)
    combined_at: datetime = field(default_factory=datetime.now)

    @property
    def variance(self) -> float:
        """Return variance (std_dev squared)."""
        return self.std_dev ** 2


# =============================================================================
# FORECAST COMBINER
# =============================================================================


class ForecastCombiner:
    """
    Combines multiple weather forecasts into a single probability distribution.

    Uses weighted averaging with uncertainty propagation that accounts for:
    1. Individual forecast uncertainty (each source's std_dev)
    2. Disagreement variance (how much sources disagree with each other)

    The combined variance is:
        σ² = Σ(w_i * σ_i²) / Σ(w_i) + Σ(w_i * (x_i - μ)²) / Σ(w_i)

    Where:
        - First term is the weighted pooled variance (individual uncertainties)
        - Second term is the disagreement variance (forecast spread)
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        min_std_dev: float = MIN_STD_DEV,
        max_std_dev: float = MAX_STD_DEV,
    ):
        """
        Initialize the forecast combiner.

        Args:
            weights: Custom weight dictionary mapping source names to weights.
                    If None, uses DEFAULT_WEIGHTS.
            min_std_dev: Minimum standard deviation floor (prevents overconfidence).
            max_std_dev: Maximum standard deviation cap (sanity check).
        """
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.min_std_dev = min_std_dev
        self.max_std_dev = max_std_dev

    def get_weight(self, source: str) -> float:
        """
        Get weight for a forecast source.

        Tries exact match first, then partial match, then default.
        """
        # Exact match
        if source in self.weights:
            return self.weights[source]

        # Partial match (case-insensitive)
        source_lower = source.lower()
        for key, weight in self.weights.items():
            if key.lower() in source_lower or source_lower in key.lower():
                return weight

        # Default fallback
        return self.weights.get("default", 1.0)

    def combine(self, forecasts: List[TemperatureForecast]) -> Optional[CombinedForecast]:
        """
        Combine multiple forecasts into a single probability distribution.

        Args:
            forecasts: List of temperature forecasts to combine.

        Returns:
            CombinedForecast with weighted mean and combined uncertainty,
            or None if no valid forecasts provided.
        """
        if not forecasts:
            logger.warning("No forecasts to combine")
            return None

        # Filter out forecasts with invalid data
        valid_forecasts = [
            f for f in forecasts
            if f.forecast_temp_f is not None and not math.isnan(f.forecast_temp_f)
        ]

        if not valid_forecasts:
            logger.warning("No valid forecasts after filtering")
            return None

        # Get weights for each forecast
        weights = [self.get_weight(f.source) for f in valid_forecasts]
        total_weight = sum(weights)

        # Normalize weights
        normalized_weights = [w / total_weight for w in weights]

        # Calculate weighted mean
        weighted_mean = sum(
            w * f.forecast_temp_f
            for w, f in zip(normalized_weights, valid_forecasts)
        )

        # Calculate combined variance using two components:
        # 1. Pooled variance (weighted average of individual variances)
        pooled_variance = sum(
            w * (f.std_dev ** 2)
            for w, f in zip(normalized_weights, valid_forecasts)
        )

        # 2. Disagreement variance (weighted variance of forecast means)
        disagreement_variance = sum(
            w * ((f.forecast_temp_f - weighted_mean) ** 2)
            for w, f in zip(normalized_weights, valid_forecasts)
        )

        # Combined variance is sum of both components
        combined_variance = pooled_variance + disagreement_variance
        combined_std_dev = math.sqrt(combined_variance)

        # Apply floor and ceiling
        combined_std_dev = max(self.min_std_dev, min(self.max_std_dev, combined_std_dev))

        # Calculate percentiles (assuming normal distribution)
        # 10th percentile: mean - 1.28 * std_dev
        # 90th percentile: mean + 1.28 * std_dev
        z_10 = 1.28155  # More precise z-score for 10th/90th percentile
        low_f = weighted_mean - z_10 * combined_std_dev
        high_f = weighted_mean + z_10 * combined_std_dev

        # Build weights used dict
        weights_used = {
            f.source: w for f, w in zip(valid_forecasts, normalized_weights)
        }

        target_date = valid_forecasts[0].target_date

        logger.info(
            f"Combined {len(valid_forecasts)} forecasts: "
            f"mean={weighted_mean:.1f}°F, std={combined_std_dev:.2f}°F"
        )

        return CombinedForecast(
            target_date=target_date,
            mean_temp_f=weighted_mean,
            std_dev=combined_std_dev,
            low_f=low_f,
            high_f=high_f,
            source_count=len(valid_forecasts),
            sources_used=[f.source for f in valid_forecasts],
            weights_used=weights_used,
            individual_forecasts=valid_forecasts,
        )

    def combine_with_custom_weights(
        self,
        forecasts: List[TemperatureForecast],
        custom_weights: Dict[str, float],
    ) -> Optional[CombinedForecast]:
        """
        Combine forecasts using custom weights for this call only.

        Useful for sensitivity analysis or testing different weight schemes.
        """
        original_weights = self.weights
        self.weights = custom_weights
        try:
            return self.combine(forecasts)
        finally:
            self.weights = original_weights


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def combine_forecasts(
    forecasts: List[TemperatureForecast],
    weights: Optional[Dict[str, float]] = None,
) -> Optional[CombinedForecast]:
    """
    Convenience function to combine forecasts with default settings.

    Args:
        forecasts: List of temperature forecasts to combine.
        weights: Optional custom weights. Uses DEFAULT_WEIGHTS if None.

    Returns:
        CombinedForecast or None if no valid forecasts.
    """
    combiner = ForecastCombiner(weights=weights)
    return combiner.combine(forecasts)
