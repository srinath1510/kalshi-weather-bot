"""
Tests for Kalshi market client module.

Uses the `responses` library to mock HTTP requests.
"""

import pytest
import responses
from datetime import datetime

from src.data.kalshi_client import (
    KalshiMarketClient,
    fetch_brackets_for_date,
    get_market_summary,
    parse_bracket_subtitle,
    calculate_implied_probability,
    format_date_for_ticker,
    parse_market_to_bracket,
)
from src.interfaces import BracketType
from src.config import KALSHI_MARKETS_URL, NYC


# =============================================================================
# TEST DATA
# =============================================================================

TARGET_DATE = "2026-01-20"
SERIES_TICKER = "KXHIGHNY"
EVENT_TICKER = "KXHIGHNY-26JAN20"


def make_market(
    ticker: str,
    event_ticker: str,
    subtitle: str,
    yes_bid: int = 25,
    yes_ask: int = 27,
    last_price: int = 26,
    volume: int = 1000,
) -> dict:
    """Create a mock Kalshi market dict."""
    return {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "subtitle": subtitle,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "last_price": last_price,
        "volume": volume,
        "status": "open",
    }


def make_api_response(markets: list) -> dict:
    """Create a mock Kalshi API response."""
    return {"markets": markets}


# Sample markets for testing
SAMPLE_MARKETS = [
    make_market(
        f"{EVENT_TICKER}-B48",
        EVENT_TICKER,
        "Below 50°",
        yes_bid=5,
        yes_ask=7,
        volume=234,
    ),
    make_market(
        f"{EVENT_TICKER}-B50",
        EVENT_TICKER,
        "50° to 52°",
        yes_bid=13,
        yes_ask=15,
        volume=567,
    ),
    make_market(
        f"{EVENT_TICKER}-B52",
        EVENT_TICKER,
        "52° to 54°",
        yes_bid=25,
        yes_ask=27,
        volume=1234,
    ),
    make_market(
        f"{EVENT_TICKER}-B54",
        EVENT_TICKER,
        "54° to 56°",
        yes_bid=23,
        yes_ask=25,
        volume=1890,
    ),
    make_market(
        f"{EVENT_TICKER}-B56",
        EVENT_TICKER,
        "56° to 58°",
        yes_bid=17,
        yes_ask=19,
        volume=678,
    ),
    make_market(
        f"{EVENT_TICKER}-B58",
        EVENT_TICKER,
        "Above 58°",
        yes_bid=11,
        yes_ask=13,
        volume=345,
    ),
]


# =============================================================================
# BRACKET SUBTITLE PARSING TESTS
# =============================================================================


class TestParseBracketSubtitle:
    """Tests for parse_bracket_subtitle function."""

    def test_parse_between_with_degree_symbol(self):
        """Test parsing 'between' subtitle with degree symbol."""
        bracket_type, lower, upper = parse_bracket_subtitle("54° to 56°")

        assert bracket_type == BracketType.BETWEEN
        assert lower == 54.0
        assert upper == 56.0

    def test_parse_between_with_fahrenheit(self):
        """Test parsing 'between' subtitle with °F."""
        bracket_type, lower, upper = parse_bracket_subtitle("54°F to 56°F")

        assert bracket_type == BracketType.BETWEEN
        assert lower == 54.0
        assert upper == 56.0

    def test_parse_between_simple(self):
        """Test parsing 'between' subtitle without symbols."""
        bracket_type, lower, upper = parse_bracket_subtitle("54 to 56")

        assert bracket_type == BracketType.BETWEEN
        assert lower == 54.0
        assert upper == 56.0

    def test_parse_greater_than_above(self):
        """Test parsing 'greater than' subtitle with 'Above'."""
        bracket_type, lower, upper = parse_bracket_subtitle("Above 58°")

        assert bracket_type == BracketType.GREATER_THAN
        assert lower == 58.0
        assert upper is None

    def test_parse_greater_than_text(self):
        """Test parsing 'greater than' subtitle with 'Greater than'."""
        bracket_type, lower, upper = parse_bracket_subtitle("Greater than 58")

        assert bracket_type == BracketType.GREATER_THAN
        assert lower == 58.0
        assert upper is None

    def test_parse_greater_than_symbol(self):
        """Test parsing 'greater than' subtitle with '>'."""
        bracket_type, lower, upper = parse_bracket_subtitle("> 58°F")

        assert bracket_type == BracketType.GREATER_THAN
        assert lower == 58.0
        assert upper is None

    def test_parse_greater_than_or_above(self):
        """Test parsing 'greater than' subtitle with 'X° or above'."""
        bracket_type, lower, upper = parse_bracket_subtitle("24° or above")

        assert bracket_type == BracketType.GREATER_THAN
        assert lower == 24.0
        assert upper is None

    def test_parse_less_than_below(self):
        """Test parsing 'less than' subtitle with 'Below'."""
        bracket_type, lower, upper = parse_bracket_subtitle("Below 50°")

        assert bracket_type == BracketType.LESS_THAN
        assert lower is None
        assert upper == 50.0

    def test_parse_less_than_text(self):
        """Test parsing 'less than' subtitle with 'Less than'."""
        bracket_type, lower, upper = parse_bracket_subtitle("Less than 50")

        assert bracket_type == BracketType.LESS_THAN
        assert lower is None
        assert upper == 50.0

    def test_parse_less_than_symbol(self):
        """Test parsing 'less than' subtitle with '<'."""
        bracket_type, lower, upper = parse_bracket_subtitle("< 50°F")

        assert bracket_type == BracketType.LESS_THAN
        assert lower is None
        assert upper == 50.0

    def test_parse_less_than_or_below(self):
        """Test parsing 'less than' subtitle with 'X° or below'."""
        bracket_type, lower, upper = parse_bracket_subtitle("15° or below")

        assert bracket_type == BracketType.LESS_THAN
        assert lower is None
        assert upper == 15.0

    def test_parse_invalid_subtitle_raises(self):
        """Test that invalid subtitle raises ValueError."""
        with pytest.raises(ValueError):
            parse_bracket_subtitle("Invalid bracket text")

    def test_parse_empty_subtitle_raises(self):
        """Test that empty subtitle raises ValueError."""
        with pytest.raises(ValueError):
            parse_bracket_subtitle("")


# =============================================================================
# IMPLIED PROBABILITY TESTS
# =============================================================================


class TestCalculateImpliedProbability:
    """Tests for calculate_implied_probability function."""

    def test_mid_market_calculation(self):
        """Test mid-market probability calculation."""
        prob = calculate_implied_probability(25, 27)
        # Mid = 26, so prob = 0.26
        assert abs(prob - 0.26) < 0.001

    def test_wide_spread(self):
        """Test with wide bid/ask spread."""
        prob = calculate_implied_probability(10, 30)
        # Mid = 20, so prob = 0.20
        assert abs(prob - 0.20) < 0.001

    def test_zero_bid(self):
        """Test with zero bid."""
        prob = calculate_implied_probability(0, 5)
        # Mid = 2.5, so prob = 0.025
        assert abs(prob - 0.025) < 0.001

    def test_both_zero(self):
        """Test with both bid and ask at zero."""
        prob = calculate_implied_probability(0, 0)
        assert prob == 0.0

    def test_high_probability(self):
        """Test with high probability market."""
        prob = calculate_implied_probability(90, 95)
        # Mid = 92.5, so prob = 0.925
        assert abs(prob - 0.925) < 0.001

    def test_at_100(self):
        """Test with market at 100."""
        prob = calculate_implied_probability(99, 100)
        assert prob == 1.0


# =============================================================================
# DATE FORMATTING TESTS
# =============================================================================


class TestFormatDateForTicker:
    """Tests for format_date_for_ticker function."""

    def test_format_january(self):
        """Test formatting January date."""
        result = format_date_for_ticker("2026-01-20")
        assert result == "26JAN20"

    def test_format_december(self):
        """Test formatting December date."""
        result = format_date_for_ticker("2026-12-25")
        assert result == "26DEC25"

    def test_format_single_digit_day(self):
        """Test formatting date with single digit day."""
        result = format_date_for_ticker("2026-01-05")
        assert result == "26JAN05"

    def test_format_different_year(self):
        """Test formatting date in different year."""
        result = format_date_for_ticker("2025-06-15")
        assert result == "25JUN15"


# =============================================================================
# MARKET PARSING TESTS
# =============================================================================


class TestParseMarketToBracket:
    """Tests for parse_market_to_bracket function."""

    def test_parse_between_market(self):
        """Test parsing a 'between' market."""
        market = make_market(
            f"{EVENT_TICKER}-B54",
            EVENT_TICKER,
            "54° to 56°",
            yes_bid=25,
            yes_ask=27,
            volume=1000,
        )
        bracket = parse_market_to_bracket(market)

        assert bracket is not None
        assert bracket.ticker == f"{EVENT_TICKER}-B54"
        assert bracket.event_ticker == EVENT_TICKER
        assert bracket.subtitle == "54° to 56°"
        assert bracket.bracket_type == BracketType.BETWEEN
        assert bracket.lower_bound == 54.0
        assert bracket.upper_bound == 56.0
        assert bracket.yes_bid == 25
        assert bracket.yes_ask == 27
        assert bracket.volume == 1000

    def test_parse_greater_than_market(self):
        """Test parsing a 'greater than' market."""
        market = make_market(
            f"{EVENT_TICKER}-B58",
            EVENT_TICKER,
            "Above 58°",
            yes_bid=11,
            yes_ask=13,
        )
        bracket = parse_market_to_bracket(market)

        assert bracket is not None
        assert bracket.bracket_type == BracketType.GREATER_THAN
        assert bracket.lower_bound == 58.0
        assert bracket.upper_bound is None

    def test_parse_less_than_market(self):
        """Test parsing a 'less than' market."""
        market = make_market(
            f"{EVENT_TICKER}-B48",
            EVENT_TICKER,
            "Below 50°",
            yes_bid=5,
            yes_ask=7,
        )
        bracket = parse_market_to_bracket(market)

        assert bracket is not None
        assert bracket.bracket_type == BracketType.LESS_THAN
        assert bracket.lower_bound is None
        assert bracket.upper_bound == 50.0

    def test_parse_invalid_market_returns_none(self):
        """Test that invalid market returns None."""
        market = {"ticker": "TEST", "subtitle": "Invalid text"}
        bracket = parse_market_to_bracket(market)
        assert bracket is None

    def test_parse_missing_fields_uses_defaults(self):
        """Test that missing fields use sensible defaults."""
        market = {
            "ticker": f"{EVENT_TICKER}-B54",
            "event_ticker": EVENT_TICKER,
            "subtitle": "54° to 56°",
            # Missing yes_bid, yes_ask, etc.
        }
        bracket = parse_market_to_bracket(market)

        assert bracket is not None
        assert bracket.yes_bid == 0
        assert bracket.yes_ask == 100
        assert bracket.volume == 0


# =============================================================================
# KALSHI MARKET CLIENT TESTS
# =============================================================================


class TestKalshiMarketClient:
    """Tests for KalshiMarketClient class."""

    @responses.activate
    def test_fetch_brackets_success(self):
        """Test successful fetch of brackets for a date."""
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response(SAMPLE_MARKETS),
            status=200,
        )

        client = KalshiMarketClient(SERIES_TICKER)
        brackets = client.fetch_brackets(TARGET_DATE)

        assert len(brackets) == 6
        # Check that brackets are sorted by lower bound
        assert brackets[0].bracket_type == BracketType.LESS_THAN  # Below 50
        assert brackets[-1].bracket_type == BracketType.GREATER_THAN  # Above 58

    @responses.activate
    def test_fetch_brackets_filters_by_date(self):
        """Test that fetch_brackets filters to the correct date."""
        # Include markets from different dates
        other_date_market = make_market(
            "KXHIGHNY-26JAN21-B54",
            "KXHIGHNY-26JAN21",  # Different date
            "54° to 56°",
        )
        all_markets = SAMPLE_MARKETS + [other_date_market]

        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response(all_markets),
            status=200,
        )

        client = KalshiMarketClient(SERIES_TICKER)
        brackets = client.fetch_brackets(TARGET_DATE)

        # Should only get brackets for TARGET_DATE
        assert len(brackets) == 6
        for bracket in brackets:
            assert "26JAN20" in bracket.event_ticker

    @responses.activate
    def test_fetch_brackets_api_error(self):
        """Test handling of API error."""
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            status=500,
        )

        client = KalshiMarketClient(SERIES_TICKER)
        brackets = client.fetch_brackets(TARGET_DATE)

        assert brackets == []

    @responses.activate
    def test_fetch_brackets_timeout(self):
        """Test handling of request timeout."""
        from requests.exceptions import Timeout

        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            body=Timeout("Connection timed out"),
        )

        client = KalshiMarketClient(SERIES_TICKER)
        brackets = client.fetch_brackets(TARGET_DATE)

        assert brackets == []

    @responses.activate
    def test_fetch_brackets_empty_response(self):
        """Test handling of empty markets response."""
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response([]),
            status=200,
        )

        client = KalshiMarketClient(SERIES_TICKER)
        brackets = client.fetch_brackets(TARGET_DATE)

        assert brackets == []

    @responses.activate
    def test_get_market_status_success(self):
        """Test getting market status."""
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response(SAMPLE_MARKETS[:1]),
            status=200,
        )

        client = KalshiMarketClient(SERIES_TICKER)
        status = client.get_market_status()

        assert status["api_available"] is True
        assert status["markets_found"] is True
        assert "timestamp" in status

    @responses.activate
    def test_get_market_status_api_error(self):
        """Test market status when API fails."""
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            status=500,
        )

        client = KalshiMarketClient(SERIES_TICKER)
        status = client.get_market_status()

        assert status["api_available"] is False
        assert "error" in status

    @responses.activate
    def test_get_available_dates(self):
        """Test getting list of available dates."""
        # Markets for multiple dates
        multi_date_markets = SAMPLE_MARKETS + [
            make_market(
                "KXHIGHNY-26JAN21-B54",
                "KXHIGHNY-26JAN21",
                "54° to 56°",
            ),
            make_market(
                "KXHIGHNY-26JAN22-B54",
                "KXHIGHNY-26JAN22",
                "54° to 56°",
            ),
        ]

        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response(multi_date_markets),
            status=200,
        )

        client = KalshiMarketClient(SERIES_TICKER)
        dates = client.get_available_dates()

        assert len(dates) == 3
        assert "2026-01-20" in dates
        assert "2026-01-21" in dates
        assert "2026-01-22" in dates
        # Should be sorted
        assert dates == sorted(dates)

    @responses.activate
    def test_default_series_ticker(self):
        """Test that default series ticker is NYC."""
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response([]),
            status=200,
        )

        client = KalshiMarketClient()
        assert client.series_ticker == NYC.series_ticker


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module convenience functions."""

    @responses.activate
    def test_fetch_brackets_for_date(self):
        """Test fetch_brackets_for_date convenience function."""
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response(SAMPLE_MARKETS),
            status=200,
        )

        brackets = fetch_brackets_for_date(TARGET_DATE, SERIES_TICKER)

        assert len(brackets) == 6

    @responses.activate
    def test_get_market_summary(self):
        """Test get_market_summary convenience function."""
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response(SAMPLE_MARKETS),
            status=200,
        )

        summary = get_market_summary(TARGET_DATE, SERIES_TICKER)

        assert summary["target_date"] == TARGET_DATE
        assert summary["bracket_count"] == 6
        assert summary["total_volume"] > 0
        assert "avg_spread_cents" in summary
        assert len(summary["brackets"]) == 6

    @responses.activate
    def test_get_market_summary_no_data(self):
        """Test get_market_summary when no data available."""
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response([]),
            status=200,
        )

        summary = get_market_summary(TARGET_DATE, SERIES_TICKER)

        assert summary["bracket_count"] == 0
        assert summary["total_volume"] == 0
        assert summary["brackets"] == []


# =============================================================================
# BRACKET BOUNDARY LOGIC TESTS
# =============================================================================


class TestBracketBoundaryLogic:
    """Tests for bracket boundary logic (contains_temp method)."""

    def test_between_contains_lower_bound(self):
        """Test that 'between' bracket contains its lower bound."""
        market = make_market(f"{EVENT_TICKER}-B54", EVENT_TICKER, "54° to 56°")
        bracket = parse_market_to_bracket(market)

        # Lower bound (54) should be included
        assert bracket.contains_temp(54.0) is True

    def test_between_contains_upper_bound(self):
        """Test that 'between' bracket contains its upper bound."""
        market = make_market(f"{EVENT_TICKER}-B54", EVENT_TICKER, "54° to 56°")
        bracket = parse_market_to_bracket(market)

        # Upper bound (56) should be included
        assert bracket.contains_temp(56.0) is True

    def test_between_contains_middle(self):
        """Test that 'between' bracket contains values in the middle."""
        market = make_market(f"{EVENT_TICKER}-B54", EVENT_TICKER, "54° to 56°")
        bracket = parse_market_to_bracket(market)

        assert bracket.contains_temp(55.0) is True

    def test_between_excludes_outside(self):
        """Test that 'between' bracket excludes values outside range."""
        market = make_market(f"{EVENT_TICKER}-B54", EVENT_TICKER, "54° to 56°")
        bracket = parse_market_to_bracket(market)

        assert bracket.contains_temp(53.0) is False
        assert bracket.contains_temp(57.0) is False

    def test_greater_than_excludes_threshold(self):
        """Test that 'greater than' bracket EXCLUDES the threshold (strictly greater)."""
        market = make_market(f"{EVENT_TICKER}-B58", EVENT_TICKER, "Above 58°")
        bracket = parse_market_to_bracket(market)

        # 58 should NOT be included (strictly greater)
        assert bracket.contains_temp(58.0) is False

    def test_greater_than_includes_above(self):
        """Test that 'greater than' bracket includes values above threshold."""
        market = make_market(f"{EVENT_TICKER}-B58", EVENT_TICKER, "Above 58°")
        bracket = parse_market_to_bracket(market)

        # 59 should be included
        assert bracket.contains_temp(59.0) is True
        assert bracket.contains_temp(100.0) is True

    def test_less_than_excludes_threshold(self):
        """Test that 'less than' bracket EXCLUDES the threshold (strictly less)."""
        market = make_market(f"{EVENT_TICKER}-B48", EVENT_TICKER, "Below 50°")
        bracket = parse_market_to_bracket(market)

        # 50 should NOT be included (strictly less)
        assert bracket.contains_temp(50.0) is False

    def test_less_than_includes_below(self):
        """Test that 'less than' bracket includes values below threshold."""
        market = make_market(f"{EVENT_TICKER}-B48", EVENT_TICKER, "Below 50°")
        bracket = parse_market_to_bracket(market)

        # 49 should be included
        assert bracket.contains_temp(49.0) is True
        assert bracket.contains_temp(0.0) is True


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @responses.activate
    def test_malformed_market_skipped(self):
        """Test that malformed markets are skipped without crashing."""
        markets = [
            SAMPLE_MARKETS[0],
            {"ticker": "BAD", "subtitle": "Not a valid bracket"},  # Invalid
            SAMPLE_MARKETS[1],
        ]
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response(markets),
            status=200,
        )

        client = KalshiMarketClient(SERIES_TICKER)
        brackets = client.fetch_brackets(TARGET_DATE)

        # Should only get 2 valid brackets
        assert len(brackets) == 2

    @responses.activate
    def test_null_values_handled(self):
        """Test handling of null values in market data."""
        market_with_nulls = {
            "ticker": f"{EVENT_TICKER}-B54",
            "event_ticker": EVENT_TICKER,
            "subtitle": "54° to 56°",
            "yes_bid": None,
            "yes_ask": None,
            "last_price": None,
            "volume": None,
        }
        responses.add(
            responses.GET,
            KALSHI_MARKETS_URL,
            json=make_api_response([market_with_nulls]),
            status=200,
        )

        client = KalshiMarketClient(SERIES_TICKER)
        brackets = client.fetch_brackets(TARGET_DATE)

        assert len(brackets) == 1
        assert brackets[0].yes_bid == 0
        assert brackets[0].yes_ask == 100
        assert brackets[0].volume == 0

    def test_invalid_json_response(self):
        """Test handling of invalid JSON response."""
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                KALSHI_MARKETS_URL,
                body="not valid json",
                status=200,
            )

            client = KalshiMarketClient(SERIES_TICKER)
            brackets = client.fetch_brackets(TARGET_DATE)

            assert brackets == []

    def test_parse_subtitle_with_extra_whitespace(self):
        """Test parsing subtitle with extra whitespace."""
        bracket_type, lower, upper = parse_bracket_subtitle("  54°   to   56°  ")

        assert bracket_type == BracketType.BETWEEN
        assert lower == 54.0
        assert upper == 56.0

    def test_parse_subtitle_case_insensitive(self):
        """Test that subtitle parsing is case insensitive."""
        bracket_type1, _, _ = parse_bracket_subtitle("ABOVE 58°")
        bracket_type2, _, _ = parse_bracket_subtitle("above 58°")
        bracket_type3, _, _ = parse_bracket_subtitle("Above 58°")

        assert bracket_type1 == BracketType.GREATER_THAN
        assert bracket_type2 == BracketType.GREATER_THAN
        assert bracket_type3 == BracketType.GREATER_THAN
