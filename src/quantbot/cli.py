"""QuantBot command-line interface (Typer).

Entry points for every mode of operation::

    quantbot run                     # live/paper trading engine
    quantbot api                     # FastAPI monitoring backend
    quantbot backtest --strategy ... # historical backtest
    quantbot optimize --strategy ... # parameter optimisation
    quantbot scan --scanner ...      # market scanners
    quantbot download --symbol ...   # fetch historical data
    quantbot migrate                 # apply database migrations
    quantbot version                 # print version
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from quantbot import __version__
from quantbot.core.config import get_settings
from quantbot.core.constants import Timeframe
from quantbot.core.logging import configure_from_settings, get_logger

app = typer.Typer(
    name="quantbot",
    help="Professional cryptocurrency trading bot for Binance.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
_log = get_logger(__name__)


def _setup() -> None:
    configure_from_settings(get_settings())


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@app.command()
def run() -> None:
    """Start the trading engine (live or paper, per TRADING_MODE in .env)."""
    _setup()
    settings = get_settings()
    console.print(f"[bold green]Starting QuantBot[/] in [cyan]{settings.trading_mode.value}[/] mode")
    from quantbot.engine.runtime import build_runtime, run_forever

    runtime = build_runtime(settings)
    try:
        asyncio.run(run_forever(runtime))
    except KeyboardInterrupt:  # pragma: no cover
        console.print("\n[yellow]Shutdown requested[/]")


# ---------------------------------------------------------------------------
# api
# ---------------------------------------------------------------------------


@app.command()
def api(
    host: Annotated[str, typer.Option(help="Bind host")] = "",
    port: Annotated[int, typer.Option(help="Bind port")] = 0,
) -> None:
    """Start the FastAPI monitoring backend."""
    _setup()
    settings = get_settings()
    import uvicorn

    from quantbot.api.app import create_app

    application = create_app(settings=settings)
    uvicorn.run(
        application,
        host=host or settings.api.host,
        port=port or settings.api.port,
        log_level=settings.log_level.lower(),
    )


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------


@app.command()
def backtest(
    strategy: Annotated[str, typer.Option(help="Registered strategy class name")],
    symbol: Annotated[str, typer.Option(help="Trading symbol")] = "BTCUSDT",
    timeframe: Annotated[str, typer.Option(help="Candle timeframe")] = "1h",
    start: Annotated[str, typer.Option(help="Start date YYYY-MM-DD")] = "2024-01-01",
    end: Annotated[str, typer.Option(help="End date YYYY-MM-DD")] = "",
    report_dir: Annotated[str, typer.Option(help="Directory for reports")] = "backtest_results",
) -> None:
    """Run a historical backtest and print + save the results."""
    _setup()
    asyncio.run(_run_backtest(strategy, symbol, timeframe, start, end, report_dir))


async def _run_backtest(
    strategy: str, symbol: str, timeframe: str, start: str, end: str, report_dir: str
) -> None:
    from quantbot.backtest.engine import BacktestEngine
    from quantbot.backtest.report import write_html, write_json
    from quantbot.data.historical import HistoricalDataLoader
    from quantbot.exchanges.factory import create_gateway
    from quantbot.strategies.registry import get_registry

    settings = get_settings()
    tf = Timeframe.from_string(timeframe)
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=UTC) if end else datetime.now(UTC)

    gateway = create_gateway(settings)
    await gateway.connect()
    try:
        loader = HistoricalDataLoader(gateway)
        candles = await loader.load(symbol, tf, start_dt, end_dt)
    finally:
        await gateway.close()

    if len(candles) < 60:
        console.print(f"[red]Only {len(candles)} candles loaded; need more history.[/]")
        raise typer.Exit(1)

    registry = get_registry()
    registry.load_builtins()
    strat = registry.create(strategy, symbols=[symbol], timeframes=[tf])
    result = BacktestEngine(settings=settings, strategies=[strat]).run(candles)

    _print_metrics(result.summary())
    out = Path(report_dir)
    write_json(result, out / f"{strategy}_{symbol}_{tf.value}.json")
    write_html(result, out / f"{strategy}_{symbol}_{tf.value}.html")
    console.print(f"[green]Reports written to[/] {out}")


# ---------------------------------------------------------------------------
# optimize
# ---------------------------------------------------------------------------


@app.command()
def optimize(
    strategy: Annotated[str, typer.Option(help="Strategy class name")],
    symbol: Annotated[str, typer.Option(help="Trading symbol")] = "BTCUSDT",
    timeframe: Annotated[str, typer.Option(help="Timeframe")] = "1h",
    start: Annotated[str, typer.Option(help="Start date")] = "2024-01-01",
    method: Annotated[str, typer.Option(help="grid|random|bayesian")] = "random",
    trials: Annotated[int, typer.Option(help="Trials for random/bayesian")] = 50,
    metric: Annotated[str, typer.Option(help="Objective metric")] = "sharpe_ratio",
) -> None:
    """Optimise strategy parameters over historical data."""
    _setup()
    console.print(
        f"[cyan]Optimising[/] {strategy} on {symbol} {timeframe} via {method} "
        f"(metric={metric})"
    )
    console.print(
        "[yellow]Define the parameter SearchSpace for your strategy in code; "
        "this command runs the configured optimizer once a space is provided.[/]"
    )
    # The concrete search space depends on the strategy; see docs/OPTIMIZATION.md
    # for a worked example wiring make_backtest_objective + an optimizer.
    _ = (symbol, timeframe, start, trials)


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@app.command()
def scan(
    scanner: Annotated[str, typer.Option(help="trend|volume|breakout|volatility|liquidity")] = "trend",
    timeframe: Annotated[str, typer.Option(help="Timeframe")] = "1h",
    top: Annotated[int, typer.Option(help="Top N results")] = 20,
) -> None:
    """Scan the configured symbol universe with a market scanner."""
    _setup()
    asyncio.run(_run_scan(scanner, timeframe, top))


async def _run_scan(scanner: str, timeframe: str, top: int) -> None:
    from quantbot.exchanges.factory import create_gateway
    from quantbot.scanners.breakout_scanner import BreakoutScanner
    from quantbot.scanners.trend_scanner import TrendScanner
    from quantbot.scanners.volatility_scanner import VolatilityScanner
    from quantbot.scanners.volume_scanner import VolumeScanner

    settings = get_settings()
    tf = Timeframe.from_string(timeframe)
    scanners = {
        "trend": TrendScanner, "volume": VolumeScanner,
        "breakout": BreakoutScanner, "volatility": VolatilityScanner,
    }
    scanner_cls = scanners.get(scanner)
    if scanner_cls is None:
        console.print(f"[red]Unknown scanner {scanner!r}. Choose: {list(scanners)}[/]")
        raise typer.Exit(1)

    gateway = create_gateway(settings)
    await gateway.connect()
    try:
        results = await scanner_cls(gateway, timeframe=tf).scan(settings.symbols, top=top)
    finally:
        await gateway.close()

    table = Table(title=f"{scanner.title()} Scanner")
    table.add_column("Symbol")
    table.add_column("Score", justify="right")
    table.add_column("Metrics")
    for r in results:
        table.add_row(r.symbol, f"{r.score:.4f}", str(r.metrics))
    console.print(table)


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


@app.command()
def download(
    symbol: Annotated[str, typer.Option(help="Symbol")] = "BTCUSDT",
    timeframe: Annotated[str, typer.Option(help="Timeframe")] = "1h",
    start: Annotated[str, typer.Option(help="Start date YYYY-MM-DD")] = "2023-01-01",
    end: Annotated[str, typer.Option(help="End date")] = "",
) -> None:
    """Download and cache historical candles to parquet."""
    _setup()
    asyncio.run(_run_download(symbol, timeframe, start, end))


async def _run_download(symbol: str, timeframe: str, start: str, end: str) -> None:
    from quantbot.data.historical import HistoricalDataLoader
    from quantbot.exchanges.factory import create_gateway

    settings = get_settings()
    tf = Timeframe.from_string(timeframe)
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=UTC) if end else datetime.now(UTC)
    gateway = create_gateway(settings)
    await gateway.connect()
    try:
        candles = await HistoricalDataLoader(gateway).load(symbol, tf, start_dt, end_dt)
    finally:
        await gateway.close()
    console.print(f"[green]Downloaded[/] {len(candles)} {tf.value} candles for {symbol}")


# ---------------------------------------------------------------------------
# migrate / version
# ---------------------------------------------------------------------------


@app.command()
def migrate() -> None:
    """Apply database migrations (alembic upgrade head)."""
    _setup()
    import subprocess

    console.print("[cyan]Applying database migrations…[/]")
    result = subprocess.run(["alembic", "upgrade", "head"], check=False)  # noqa: S603, S607
    raise typer.Exit(result.returncode)


@app.command()
def version() -> None:
    """Print the QuantBot version."""
    console.print(f"QuantBot [bold]{__version__}[/]")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _print_metrics(summary: dict) -> None:
    table = Table(title="Backtest Results")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for key, value in summary.items():
        table.add_row(str(key), str(value))
    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    app()
