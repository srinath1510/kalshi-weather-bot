"""
Kalshi Market Client for Weather Trading Bot.

Fetches and parses Kalshi market data for temperature brackets.

Key features:
- Fetches markets for NYC high temperature series (KXHIGHNY)
- Parses bracket subtitles to extract temperature bounds
- Handles all three bracket types: between, greater_than, less_than
- Calculates implied probability from bid/ask mid
"""

import logging
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple

import requests

from src.interfaces import MarketBracket, MarketDataSource, BracketType
from src.config import (
    NYC,
    KALSHI_API_BASE,
    KALSHI_MARKETS_URL,
    API_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Regex patterns for parsing bracket subtitles
# Examples: "54° to 56°", "54°F to 56°F", "54 to 56"
BETWEEN_PATTERN = re.compile(
    r"(\d+)°?\s*(?:F)?\s*to\s*(\d+)°?\s*(?:F)?",
    re.IGNORECASE
)

# Examples: "Above 56°", "Above 56°F", "Greater than 56", "> 56", "56° or above"
GREATER_THAN_PATTERN = re.compile(
    r"(?:(?:above|greater\s*than|>)\s*(\d+)|(\d+)°?\s*(?:F)?\s*or\s*above)°?\s*(?:F)?",
    re.IGNORECASE
)

# Examples: "Below 50°", "Below 50°F", "Less than 50", "< 50", "50° or below"
LESS_THAN_PATTERN = re.compile(
    r"(?:(?:below|less\s*than|<)\s*(\d+)|(\d+)°?\s*(?:F)?\s*or\s*below)°?\s*(?:F)?",
    re.IGNORECASE
)


def parse_bracket_subtitle(subtitle: str) -> Tuple[BracketType, Optional[float], Optional[float]]:
    """
    Parse a bracket subtitle to extract type and bounds.

    Args:
        subtitle: The bracket subtitle (e.g., "54° to 56°", "Above 56°", "Below 50°")

    Returns:
        Tuple of (bracket_type, lower_bound, upper_bound)
        - For BETWEEN: both bounds are set
        - For GREATER_THAN: lower_bound is the threshold, upper_bound is None
        - For LESS_THAN: lower_bound is None, upper_bound is the threshold

    Raises:
        ValueError: If subtitle cannot be parsed
    """
    # Try "between" pattern first (most common)
    match = BETWEEN_PATTERN.search(subtitle)
    if match:
        lower = float(match.group(1))
        upper = float(match.group(2))
        return (BracketType.BETWEEN, lower, upper)

    # Try "greater than" pattern
    match = GREATER_THAN_PATTERN.search(subtitle)
    if match:
        # Group 1 is "above X" format, Group 2 is "X or above" format
        threshold = float(match.group(1) or match.group(2))
        return (BracketType.GREATER_THAN, threshold, None)

    # Try "less than" pattern
    match = LESS_THAN_PATTERN.search(subtitle)
    if match:
        # Group 1 is "below X" format, Group 2 is "X or below" format
        threshold = float(match.group(1) or match.group(2))
        return (BracketType.LESS_THAN, None, threshold)

    raise ValueError(f"Could not parse bracket subtitle: {subtitle}")


def calculate_implied_probability(yes_bid: int, yes_ask: int) -> float:
    """
    Calculate implied probability from bid/ask prices.

    Uses the mid-market price as the probability estimate.

    Args:
        yes_bid: Best bid price in cents (0-99)
        yes_ask: Best ask price in cents (1-100)

    Returns:
        Implied probability as a float between 0.0 and 1.0
    """
    if yes_bid == 0 and yes_ask == 0:
        return 0.0
    if yes_bid >= 100 or yes_ask >= 100:
        # Handle edge case where market is at 100
        return 1.0

    # Mid-market price
    mid = (yes_bid + yes_ask) / 2.0
    return mid / 100.0


def format_date_for_ticker(target_date: str) -> str:
    """
    Format a date string for matching Kalshi event tickers.

    Args:
        target_date: Date in YYYY-MM-DD format

    Returns:
        Date formatted as used in Kalshi tickers (e.g., "26JAN12" for 2026-01-12)
    """
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    # Kalshi uses format like "26JAN12" (YY + MON + DD)
    return dt.strftime("%y%b%d").upper()


def parse_market_to_bracket(market: Dict) -> Optional[MarketBracket]:
    """
    Parse a Kalshi market dict into a MarketBracket.

    Args:
        market: Market dict from Kalshi API

    Returns:
        MarketBracket or None if parsing fails
    """
    try:
        ticker = market.get("ticker", "")
        event_ticker = market.get("event_ticker", "")
        subtitle = market.get("subtitle", "")

        # Parse the subtitle to get bracket type and bounds
        bracket_type, lower_bound, upper_bound = parse_bracket_subtitle(subtitle)

        # Get pricing info
        yes_bid = market.get("yes_bid", 0) or 0
        yes_ask = market.get("yes_ask", 100) or 100
        last_price = market.get("last_price", 0) or 0
        volume = market.get("volume", 0) or 0

        # Calculate implied probability
        implied_prob = calculate_implied_probability(yes_bid, yes_ask)

        return MarketBracket(
            ticker=ticker,
            event_ticker=event_ticker,
            subtitle=subtitle,
            bracket_type=bracket_type,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            last_price=last_price,
            volume=volume,
            implied_prob=implied_prob,
        )
    except (ValueError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse market {market.get('ticker', 'unknown')}: {e}")
        return None


class KalshiMarketClient(MarketDataSource):
    """Fetches and parses Kalshi temperature market data."""

    def __init__(self, series_ticker: str = None):
        """
        Initialize the Kalshi market client.

        Args:
            series_ticker: The series ticker to fetch (default: NYC high temp)
        """
        self.series_ticker = series_ticker or NYC.series_ticker
        self._last_status: Optional[Dict] = None

    def _get_headers(self) -> Dict:
        """Return headers for Kalshi API requests."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _fetch_markets(self, event_ticker: str = None) -> List[Dict]:
        """
        Fetch markets from Kalshi API.

        Args:
            event_ticker: Optional specific event ticker to filter by

        Returns:
            List of market dicts from API
        """
        try:
            params = {
                "limit": 100,
                "status": "open",
            }

            # Filter by series ticker
            if event_ticker:
                params["event_ticker"] = event_ticker
            else:
                params["series_ticker"] = self.series_ticker

            response = requests.get(
                KALSHI_MARKETS_URL,
                params=params,
                headers=self._get_headers(),
                timeout=API_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            # Kalshi API returns markets in a "markets" key
            markets = data.get("markets", [])
            return markets
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch Kalshi markets: {e}")
            return []
        except (ValueError, KeyError) as e:
            logger.warning(f"Failed to parse Kalshi markets response: {e}")
            return []

    def fetch_brackets(self, target_date: str) -> List[MarketBracket]:
        """
        Fetch all brackets for a target date's temperature market.

        Args:
            target_date: Date in YYYY-MM-DD format

        Returns:
            List of MarketBracket objects for the target date
        """
        # Format the date for matching event tickers
        date_str = format_date_for_ticker(target_date)
        expected_event_ticker = f"{self.series_ticker}-{date_str}"

        # Fetch all markets for this series
        markets = self._fetch_markets()

        if not markets:
            # Try fetching with specific event ticker
            markets = self._fetch_markets(event_ticker=expected_event_ticker)

        # Filter to target date and parse
        brackets = []
        for market in markets:
            event_ticker = market.get("event_ticker", "")

            # Check if this market is for the target date
            if date_str not in event_ticker:
                continue

            bracket = parse_market_to_bracket(market)
            if bracket:
                brackets.append(bracket)

        # Sort brackets by lower bound (or upper bound for less_than)
        brackets.sort(key=lambda b: b.lower_bound if b.lower_bound is not None else (b.upper_bound or 0))

        return brackets

    def fetch_all_open_markets(self) -> List[MarketBracket]:
        """
        Fetch all open markets for the series (all dates).

        Returns:
            List of MarketBracket objects for all open markets
        """
        markets = self._fetch_markets()

        brackets = []
        for market in markets:
            bracket = parse_market_to_bracket(market)
            if bracket:
                brackets.append(bracket)

        return brackets

    def get_market_status(self) -> Dict:
        """
        Get current market status.

        Returns:
            Dict with market status information
        """
        try:
            # Fetch a single market to check API status
            response = requests.get(
                KALSHI_MARKETS_URL,
                params={"series_ticker": self.series_ticker, "limit": 1},
                headers=self._get_headers(),
                timeout=API_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            markets = data.get("markets", [])
            self._last_status = {
                "api_available": True,
                "markets_found": len(markets) > 0,
                "timestamp": datetime.now().isoformat(),
            }
            return self._last_status
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to get market status: {e}")
            self._last_status = {
                "api_available": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }
            return self._last_status

    def get_available_dates(self) -> List[str]:
        """
        Get list of dates with open markets.

        Returns:
            List of dates in YYYY-MM-DD format
        """
        markets = self._fetch_markets()

        dates = set()
        for market in markets:
            event_ticker = market.get("event_ticker", "")
            # Extract date from event ticker (e.g., "KXHIGHNY-26JAN12")
            if "-" in event_ticker:
                date_part = event_ticker.split("-")[-1]
                try:
                    # Parse the date part (e.g., "26JAN12" -> 2026-01-12)
                    dt = datetime.strptime(date_part, "%y%b%d")
                    dates.add(dt.strftime("%Y-%m-%d"))
                except ValueError:
                    continue

        return sorted(dates)


def fetch_brackets_for_date(
    target_date: str,
    series_ticker: str = None,
) -> List[MarketBracket]:
    """
    Convenience function to fetch brackets for a specific date.

    Args:
        target_date: Date in YYYY-MM-DD format
        series_ticker: Optional series ticker (default: NYC high temp)

    Returns:
        List of MarketBracket objects
    """
    client = KalshiMarketClient(series_ticker)
    return client.fetch_brackets(target_date)


def get_market_summary(target_date: str, series_ticker: str = None) -> Dict:
    """
    Get a summary of market data for a target date.

    Args:
        target_date: Date in YYYY-MM-DD format
        series_ticker: Optional series ticker (default: NYC high temp)

    Returns:
        Dict with market summary including total volume, bracket count, etc.
    """
    brackets = fetch_brackets_for_date(target_date, series_ticker)

    if not brackets:
        return {
            "target_date": target_date,
            "bracket_count": 0,
            "total_volume": 0,
            "brackets": [],
        }

    total_volume = sum(b.volume for b in brackets)
    avg_spread = sum(b.yes_ask - b.yes_bid for b in brackets) / len(brackets)

    return {
        "target_date": target_date,
        "bracket_count": len(brackets),
        "total_volume": total_volume,
        "avg_spread_cents": round(avg_spread, 1),
        "brackets": [
            {
                "subtitle": b.subtitle,
                "implied_prob": round(b.implied_prob, 3),
                "bid": b.yes_bid,
                "ask": b.yes_ask,
                "volume": b.volume,
            }
            for b in brackets
        ],
    }
