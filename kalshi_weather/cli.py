"""Command-line interface for Kalshi Weather Bot."""

import click
from datetime import datetime, timedelta

from kalshi_weather import __version__, get_city, list_cities
from kalshi_weather.contracts import HighTempContract
from kalshi_weather.utils import setup_logging


@click.group()
@click.version_option(version=__version__)
@click.option("--debug", is_flag=True, help="Enable debug logging")
def main(debug: bool):
    """Kalshi Weather Bot - Weather analysis for temperature markets."""
    setup_logging(level="DEBUG" if debug else "INFO")


@main.command()
@click.option("--city", "-c", default="NYC", help="City code (NYC, CHI, LAX, MIA, AUS)")
@click.option("--date", "-d", default=None, help="Target date (YYYY-MM-DD)")
def status(city: str, date: str):
    """Check market status and available dates."""
    try:
        city_config = get_city(city)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        return

    contract = HighTempContract(city_config)
    market_status = contract.get_market_status()

    click.echo(f"\n{'='*50}")
    click.echo(f"Market Status: {city_config.name}")
    click.echo(f"{'='*50}")
    click.echo(f"API Available: {market_status.get('api_available')}")
    click.echo(f"Markets Found: {market_status.get('markets_found')}")
    click.echo(f"Series Ticker: {market_status.get('series_ticker')}")

    dates = contract.get_available_dates()
    if dates:
        click.echo(f"\nAvailable Dates ({len(dates)}):")
        for d in dates[:5]:
            click.echo(f"  - {d}")
        if len(dates) > 5:
            click.echo(f"  ... and {len(dates) - 5} more")


@main.command()
@click.option("--city", "-c", default="NYC", help="City code (NYC, CHI, LAX, MIA, AUS)")
@click.option("--date", "-d", default=None, help="Target date (YYYY-MM-DD)")
def brackets(city: str, date: str):
    """Fetch and display market brackets."""
    try:
        city_config = get_city(city)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        return

    contract = HighTempContract(city_config)

    if not date:
        dates = contract.get_available_dates()
        if not dates:
            click.echo("No open markets found", err=True)
            return
        date = dates[0]

    brackets = contract.fetch_brackets(date)

    click.echo(f"\n{'='*60}")
    click.echo(f"Brackets for {city_config.name} - {date}")
    click.echo(f"{'='*60}")

    if not brackets:
        click.echo("No brackets found for this date")
        return

    click.echo(f"\n{'Bracket':<20} {'Type':<14} {'Bid':>5} {'Ask':>5} {'Prob':>7} {'Volume':>8}")
    click.echo("-" * 65)

    for b in brackets:
        click.echo(
            f"{b.subtitle:<20} {b.bracket_type.value:<14} "
            f"{b.yes_bid:>4}¢ {b.yes_ask:>4}¢ {b.implied_prob:>6.1%} {b.volume:>8,}"
        )

    total_prob = sum(b.implied_prob for b in brackets)
    total_vol = sum(b.volume for b in brackets)
    click.echo("-" * 65)
    click.echo(f"{'Total':<20} {'':<14} {'':<5} {'':<5} {total_prob:>6.1%} {total_vol:>8,}")


@main.command()
@click.option("--city", "-c", default="NYC", help="City code (NYC, CHI, LAX, MIA, AUS)")
@click.option("--date", "-d", default=None, help="Target date (YYYY-MM-DD)")
def forecasts(city: str, date: str):
    """Fetch and display weather forecasts."""
    try:
        city_config = get_city(city)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        return

    if not date:
        date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    contract = HighTempContract(city_config)
    forecasts = contract.fetch_forecasts(date)

    click.echo(f"\n{'='*60}")
    click.echo(f"Forecasts for {city_config.name} - {date}")
    click.echo(f"{'='*60}")

    if not forecasts:
        click.echo("No forecasts available")
        return

    click.echo(f"\n{'Source':<25} {'Temp':>8} {'Low':>8} {'High':>8} {'StdDev':>8}")
    click.echo("-" * 60)

    for f in forecasts:
        click.echo(
            f"{f.source:<25} {f.forecast_temp_f:>7.1f}° "
            f"{f.low_f:>7.1f}° {f.high_f:>7.1f}° {f.std_dev:>7.1f}°"
        )


@main.command()
def cities():
    """List available cities."""
    click.echo("\nAvailable Cities:")
    click.echo("-" * 30)
    for code in list_cities():
        city = get_city(code)
        click.echo(f"  {code:<5} - {city.name}")


if __name__ == "__main__":
    main()
