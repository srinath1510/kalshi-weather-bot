"""
Edge Detector Module (Module 3A & 3B)

Responsible for:
1. Orchestrating the probability calculation (combining forecasts + adjusting for observations).
2. Comparing model probabilities vs market prices.
3. Identifying trading edges (value) considering fees.
4. Generating human-readable trading signals.
"""

import logging
from typing import List, Optional

from kalshi_weather.core.models import (
    EdgeEngine,
    TemperatureForecast,
    DailyObservation,
    MarketBracket,
    TradingSignal,
)
from kalshi_weather.config.settings import (
    MIN_EDGE_THRESHOLD,
    KALSHI_FEE_RATE,
)
from kalshi_weather.engine.probability import (
    combine_forecasts,
    adjust_forecast_with_observations,
    BracketProbabilityCalculator,
)

logger = logging.getLogger(__name__)


class EdgeDetector(EdgeEngine):
    """
    Implementation of the Edge Engine.
    
    Orchestrates the pipeline:
    Forecasts -> CombinedForecast -> Observation Adjustment -> AdjustedForecast -> Bracket Probabilities -> Signals
    """

    def __init__(self, fee_rate: float = KALSHI_FEE_RATE):
        self.fee_rate = fee_rate
        self.prob_calculator = BracketProbabilityCalculator()

    def analyze(
        self,
        forecasts: List[TemperatureForecast],
        observation: Optional[DailyObservation],
        brackets: List[MarketBracket],
        min_edge: float = MIN_EDGE_THRESHOLD
    ) -> List[TradingSignal]:
        """
        Analyze market and return trading signals.
        
        Args:
            forecasts: List of weather forecasts.
            observation: Current day's station observation (optional).
            brackets: List of Kalshi market brackets.
            min_edge: Minimum edge required to generate a signal.
            
        Returns:
            List of TradingSignal objects sorted by edge strength.
        """
        if not forecasts:
            logger.warning("No forecasts provided for edge analysis")
            return []

        if not brackets:
            logger.warning("No brackets provided for edge analysis")
            return []

        # 1. Combine Forecasts
        logger.info(f"Combining {len(forecasts)} forecasts...")
        combined = combine_forecasts(forecasts)
        if not combined:
            logger.error("Failed to combine forecasts")
            return []

        # 2. Adjust for Observations
        logger.info("Adjusting for observations...")
        adjusted = adjust_forecast_with_observations(combined, observation)

        # 3. Calculate Model Probabilities
        logger.info("Calculating bracket probabilities...")
        # We use the calculator directly on the adjusted forecast
        model_probs = self.prob_calculator.calculate_from_adjusted_forecast(
            adjusted, brackets
        )

        # 4. Find Edges
        signals = []
        for bp in model_probs:
            # We calculate edge for both YES (Long) and NO (Short) directions
            
            # --- Check LONG (Buy YES) ---
            # Cost to enter is the Ask price
            entry_cost = bp.bracket.yes_ask / 100.0
            
            if 0 < entry_cost < 1.0: # Filter out invalid prices
                # EV calculation with fees:
                # Profit = 1.00 - Fee (on win)
                # EV = Prob * (1 - Fee) - Cost
                # Note: Fee is usually on Net Winnings or Notional. 
                # Assuming Fee on Notional (1.00) or Profit (1.00 - Cost).
                # Implementation Plan says "effective_price = price + fees".
                # If we assume 10% fee means we pay 10% on profit:
                # Payout = 1.0 - (1.0 - Cost) * Fee_Rate? 
                # Or simpler: Kalshi takes fee on retrieval.
                # Let's use a conservative approach: Payout = 1.0 * (1 - Fee_Rate)
                # This approximates the "vig".
                
                # Using the logic: Edge = Model_Prob - Effective_Price
                # Effective_Price = Ask / (1 - Fee_Rate)? No.
                # If I pay 50c, and payout is 90c (10% fee), my break even is 50/90 = 55.5%.
                # So Effective Price = Price / (1 - Fee_Rate) ??
                
                # Let's stick to the simplest interpretation of EV > 0.
                # EV = (Model_Prob * (1.0 - self.fee_rate)) - entry_cost
                # Edge = EV
                
                # However, usually Edge is defined as Prob - Price.
                # Let's define Edge = Metric to compare.
                # Let's use Expected Return on Investment (ROI) or just absolute EV per dollar.
                
                # Plan says: "effective_price = price + fees (approximate)"
                # "Compare model_prob vs market_prob"
                # "Threshold > 8% edge"
                
                # Let's treat fee as an adder to price.
                # effective_price = entry_cost + (self.fee_rate * entry_cost)? 
                # Or effective_price = entry_cost / (1 - fee)?
                # If Kalshi fee is 10% of profit.
                # Let's assume simplest: Effective Price = Ask Price.
                # AND we just subtract a fixed fee buffer (the fee rate) from the edge.
                # But let's follow the user instruction "price + fees".
                # If I buy at 0.50, I pay 0.50. Fee might be charged on settlement.
                
                # Let's try: effective_price = entry_cost + (entry_cost * self.fee_rate) 
                # (Approximate transaction fee logic, though Kalshi is settlement fee).
                
                # Better logic for Settlement Fee (percent of winnings):
                # We need Model_Prob > Cost / (1 - Fee) ?
                # No, if fee is on total payout: Model_Prob * (1 - Fee) > Cost.
                # => Model_Prob > Cost / (1 - Fee).
                # So Effective Price = Cost / (1 - Fee).
                
                # If Fee Rate is 0.10 (10%).
                effective_ask = entry_cost / (1.0 - self.fee_rate)
                
                edge_long = bp.model_prob - effective_ask
                
                if edge_long > min_edge:
                    signals.append(TradingSignal(
                        bracket=bp.bracket,
                        direction="YES",
                        model_prob=bp.model_prob,
                        market_prob=bp.market_prob, # This is mid-point
                        edge=edge_long,
                        confidence=self._calculate_confidence(edge_long, adjusted.std_dev),
                        reasoning=(
                            f"Model ({bp.model_prob:.1%}) > Market Ask ({entry_cost:.1%}) + Fees. "
                            f"Model Mean: {adjusted.mean_temp_f:.1f}F"
                        )
                    ))

            # --- Check SHORT (Buy NO / Sell YES) ---
            # To go short YES, we Sell at the Bid.
            # Revenue = Bid price.
            # We lose 1.00 if YES happens.
            # EV = Bid - (Model_Prob * 1.00) ? 
            # Wait, Shorting on Kalshi:
            # You buy a "NO" contract usually? Or you sell a "YES" position?
            # MarketBracket has `yes_bid`. This is the price someone will pay us for YES.
            # So we sell YES at `yes_bid`. We collect `yes_bid`.
            # If outcome is YES, we pay 1.00. (Net - (1.00 - Bid)).
            # If outcome is NO, we pay 0.00. (Net + Bid).
            # Fee applies on profit?
            # Max possible profit is `yes_bid`.
            # EV = (1 - Model_Prob) * (yes_bid * (1-Fee)) - (Model_Prob * (1.00 - yes_bid))? 
            # This is complex.
            # Simplified: We treat "Sell YES at X" as "Buy NO at 1-X".
            # Implied NO Price = 1.00 - yes_bid.
            # Model NO Prob = 1.00 - model_prob.
            # Cost = Implied NO Price.
            # Effective Cost = Cost / (1 - Fee).
            # Edge = Model NO Prob - Effective Cost.
            
            entry_price_no = 1.00 - (bp.bracket.yes_bid / 100.0)
            
            if 0 < entry_price_no < 1.0:
                 effective_ask_no = entry_price_no / (1.0 - self.fee_rate)
                 model_prob_no = 1.0 - bp.model_prob
                 
                 edge_short = model_prob_no - effective_ask_no
                 
                 if edge_short > min_edge:
                    signals.append(TradingSignal(
                        bracket=bp.bracket,
                        direction="NO",
                        model_prob=bp.model_prob,
                        market_prob=bp.market_prob,
                        edge=edge_short,
                        confidence=self._calculate_confidence(edge_short, adjusted.std_dev),
                        reasoning=(
                            f"Model NO ({model_prob_no:.1%}) > Implied Market NO ({entry_price_no:.1%}) + Fees. "
                            f"Model Mean: {adjusted.mean_temp_f:.1f}F"
                        )
                    ))

        # Sort signals by edge strength (descending)
        signals.sort(key=lambda s: s.edge, reverse=True)
        
        return signals

    def _calculate_confidence(self, edge: float, std_dev: float) -> float:
        """
        Calculate a confidence score (0-1) for the signal.
        
        Factors:
        - Magnitude of edge (larger is better)
        - Forecast uncertainty (lower std dev is better)
        """
        # 1. Edge Score: Map 0.05-0.20 edge to 0.5-1.0
        edge_score = min(1.0, max(0.0, (edge - 0.05) / 0.15 * 0.5 + 0.5))
        
        # 2. Uncertainty Score: Map 1.5-5.0 std dev to 1.0-0.5
        # Lower std dev = higher confidence
        unc_score = max(0.0, min(1.0, 1.0 - (std_dev - 1.5) / 3.5 * 0.5))
        
        return (edge_score + unc_score) / 2.0
