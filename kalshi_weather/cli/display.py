"""
Terminal Dashboard for Kalshi Weather Bot.

Uses Rich to display real-time analysis, forecasts, and trading signals.
"""

from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

from kalshi_weather.core.models import MarketAnalysis, TradingSignal, MarketBracket

class Dashboard:
    """
    Terminal User Interface for the weather bot.
    """

    def __init__(self):
        self.console = Console()
        self.layout = Layout()
        self._setup_layout()

    def _setup_layout(self):
        """Define the grid layout."""
        self.layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )

        self.layout["main"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )

        self.layout["left"].split(
            Layout(name="forecasts", ratio=1),
            Layout(name="observations", size=10),
        )

        self.layout["right"].split(
            Layout(name="brackets", ratio=1),
            Layout(name="signals", ratio=1),
        )

    def generate_header(self, analysis: Optional[MarketAnalysis] = None) -> Panel:
        """Create header panel."""
        if analysis:
            title = f"Kalshi Weather Bot - {analysis.city} - Target: {analysis.target_date}"
            sub_text = f"Last Updated: {datetime.now().strftime('%H:%M:%S')}"
        else:
            title = "Kalshi Weather Bot"
            sub_text = "Initializing..."
        
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_row(f"[b]{title}[/b]")
        grid.add_row(f"[dim]{sub_text}[/dim]")
        
        return Panel(grid, style="bold white on blue")

    def generate_forecast_table(self, analysis: MarketAnalysis) -> Panel:
        """Create forecast table."""
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Source")
        table.add_column("Temp", justify="right")
        table.add_column("StdDev", justify="right")
        
        # Individual Forecasts
        for f in analysis.forecasts:
            table.add_row(
                f.source,
                f"{f.forecast_temp_f:.1f}°F",
                f"{f.std_dev:.1f}°F"
            )
            
        table.add_section()
        
        # Combined
        table.add_row(
            "[b]Combined Mean[/b]",
            f"[b]{analysis.forecast_mean:.1f}°F[/b]",
            f"{analysis.forecast_std:.1f}°F",
            style="yellow"
        )
        
        return Panel(table, title="Weather Forecasts", border_style="cyan")

    def generate_observation_panel(self, analysis: MarketAnalysis) -> Panel:
        """Create observation summary."""
        if not analysis.observation:
            return Panel("No observation data available", title="Live Observations", border_style="white")
            
        obs = analysis.observation
        
        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_column(justify="right")
        
        grid.add_row("Station:", obs.station_id)
        grid.add_row("Observed High:", f"[b]{obs.observed_high_f:.1f}°F[/b]")
        grid.add_row("Actual High (Est):", f"{obs.possible_actual_high_low:.1f}° - {obs.possible_actual_high_high:.1f}°")
        grid.add_row("Readings:", str(len(obs.readings)))
        
        # Show last reading time and value if available
        if obs.readings:
            last = obs.readings[-1]
            grid.add_row("Last Reading:", f"{last.timestamp.astimezone().strftime('%H:%M')} ({last.reported_temp_f}°F)")
        
        return Panel(grid, title="Live Observations (KNYC)", border_style="green")

    def generate_bracket_table(self, analysis: MarketAnalysis) -> Panel:
        """Create market brackets table."""
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Bracket")
        table.add_column("Bid/Ask", justify="right")
        table.add_column("Mkt %", justify="right")
        table.add_column("Model %", justify="right")
        
        # Assuming analysis.signals might have bracket probabilities? 
        # Actually analysis.brackets has brackets. 
        # But where are the calculated probabilities? 
        # The Edge Detector returns Signals, but we might want to display ALL brackets with model prob.
        # But 'MarketAnalysis' definition imports TradingSignal but doesn't explicitly store 'BracketProbability'.
        # However, for just display, maybe we iterate through signals to find model prob? 
        # Or we should update MarketAnalysis to include detailed bracket analysis.
        # For now, I'll rely on what's in brackets (just market data) unless I can get model data.
        # Wait, the signals list contains the opportunities.
        
        # Let's map subtitle to signal for highlighting
        signal_map = {s.bracket.subtitle: s for s in analysis.signals}
        
        for b in analysis.brackets:
            # Finding model prob: simple approach, if we have a signal use it, else ???
            # Ideally the analysis object should have this.
            # But let's just show market data for now, and highlight signals.
            
            pricing = f"{b.yes_bid}¢ / {b.yes_ask}¢"
            mkt_prob = f"{b.implied_prob:.1%}"
            
            style = "white"
            model_prob_display = "-"
            
            if b.subtitle in signal_map:
                sig = signal_map[b.subtitle]
                style = "bold green" if sig.direction == "YES" else "bold red"
                model_prob_display = f"{sig.model_prob:.1%}"
                # If short, maybe show differently?
            
            table.add_row(
                b.subtitle,
                pricing,
                mkt_prob,
                model_prob_display,
                style=style
            )
            
        return Panel(table, title="Market Brackets", border_style="blue")

    def generate_signals_panel(self, analysis: MarketAnalysis) -> Panel:
        """Create signals list."""
        if not analysis.signals:
            return Panel(
                Align.center("[dim]No significant trading edges detected[/dim]"),
                title="Trading Signals",
                border_style="white"
            )
            
        table = Table(box=box.ROUNDED, expand=True, show_header=False)
        table.add_column(ratio=1)
        
        for sig in analysis.signals:
            direction_color = "green" if sig.direction == "YES" else "red"
            
            # Construct a rich text summary
            content = Text()
            content.append(f"{sig.direction} ", style=f"bold {direction_color}")
            content.append(f"{sig.bracket.subtitle}", style="bold white")
            content.append(f"\nEdge: {sig.edge * 100:+.1f}% | Conf: {sig.confidence:.0%}")
            content.append(f"\n{sig.reasoning}", style="dim")
            
            table.add_row(content)
            
        return Panel(table, title=f"Signals ({len(analysis.signals)})", border_style="magenta")

    def update(self, analysis: MarketAnalysis):
        """Update the dashboard with new analysis."""
        
        self.layout["header"].update(self.generate_header(analysis))
        self.layout["forecasts"].update(self.generate_forecast_table(analysis))
        self.layout["observations"].update(self.generate_observation_panel(analysis))
        self.layout["brackets"].update(self.generate_bracket_table(analysis))
        self.layout["signals"].update(self.generate_signals_panel(analysis))
        
        # Simple footer
        status_text = "Running... Press Ctrl+C to exit."
        self.layout["footer"].update(Panel(Align.center(status_text), style="dim"))
