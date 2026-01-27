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


@main.command()
@click.option("--city", "-c", default="NYC", help="City code (NYC, CHI, LAX, MIA, AUS)")
def run(city: str):
    """Run the interactive dashboard bot."""
    from kalshi_weather.cli.bot import run_bot
    run_bot(city)


@main.command()
@click.option("--city", "-c", default="NYC", help="City code (NYC, CHI, LAX, MIA, AUS)")
@click.option("--date", "-d", default=None, help="Target date (YYYY-MM-DD), defaults to yesterday")
@click.option("--days", "-n", default=None, type=int, help="Show last N days of settlements")
def settlement(city: str, date: str, days: int):
    """Show historical settlement temperatures."""
    from kalshi_weather.data.historical import fetch_settlement, fetch_settlement_range

    try:
        city_config = get_city(city)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        return

    click.echo(f"\n{'='*55}")
    click.echo(f"Settlement Data: {city_config.name}")
    click.echo(f"{'='*55}")

    if days:
        # Show last N days
        end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        records = fetch_settlement_range(start_date, end_date, city_config)

        if not records:
            click.echo("No settlement data available for this period", err=True)
            return

        click.echo(f"\n{'Date':<12} {'High':>8} {'Low':>8}")
        click.echo("-" * 30)

        for r in sorted(records, key=lambda x: x.date, reverse=True):
            click.echo(f"{r.date:<12} {r.settlement_high_f:>7.1f}° {r.settlement_low_f:>7.1f}°")

        click.echo("-" * 30)
        click.echo(f"Source: {records[0].source}")
    else:
        # Show single date (default: yesterday)
        if not date:
            date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        record = fetch_settlement(date, city_config)

        if not record:
            click.echo(f"No settlement data available for {date}", err=True)
            return

        click.echo(f"\nDate:            {record.date}")
        click.echo(f"High Temp:       {record.settlement_high_f:.0f}°F")
        click.echo(f"Low Temp:        {record.settlement_low_f:.0f}°F")
        click.echo(f"Source:          {record.source}")
        click.echo(f"Station:         {record.station_name}")


if __name__ == "__main__":
    main()
