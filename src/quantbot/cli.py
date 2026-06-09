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
# serve (engine + dashboard API in one process)
# ---------------------------------------------------------------------------


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="API bind host")] = "",
    port: Annotated[int, typer.Option(help="API bind port")] = 0,
) -> None:
    """Run the trading engine AND the dashboard API together in ONE process.

    This is how you use the dashboard with a live bot: the API shares the running
    engine's in-memory state, so the panels show real data and the WebSocket pushes
    live updates. (Running ``quantbot api`` separately would show empty data — a
    different process can't see the engine's state.)
    """
    _setup()
    settings = get_settings()
    console.print(
        f"[bold green]Starting QuantBot[/] (engine + dashboard) in "
        f"[cyan]{settings.trading_mode.value}[/] mode"
    )
    import uvicorn

    from quantbot.api.app import create_app
    from quantbot.api.dependencies import AppState
    from quantbot.engine.runtime import build_runtime

    runtime = build_runtime(settings)
    state = AppState(
        settings=settings,
        portfolio=runtime.portfolio,
        risk_engine=runtime.risk_engine,
        trading_engine=runtime.engine,
        strategies=runtime.strategies,
    )
    application = create_app(settings=settings, state=state, event_bus=runtime.event_bus)

    bind_host = host or settings.api.host
    bind_port = port or settings.api.port

    async def _start_engine() -> None:
        """Bring the engine up WITHOUT taking the dashboard down if it fails."""
        try:
            await runtime.gateway.connect()
            await runtime.engine.start()
            console.print("[green]Engine connected and trading.[/]")
        except Exception as exc:  # noqa: BLE001 - keep the dashboard reachable
            console.print(
                f"[red]Engine failed to start:[/] {exc}\n"
                f"[yellow]The dashboard stays up (showing empty/last state). "
                f"Fix the cause and restart.[/]"
            )

    async def _serve() -> None:
        config = uvicorn.Config(
            application, host=bind_host, port=bind_port,
            log_level=settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        # Start the API FIRST (so the dashboard is reachable immediately), then bring
        # the engine up concurrently. An engine startup error no longer prevents the
        # API from listening on :8000.
        server_task = asyncio.create_task(server.serve())
        console.print(
            f"[green]Dashboard API on[/] http://{bind_host}:{bind_port}  (docs at /docs)"
        )
        await _start_engine()
        try:
            await server_task  # blocks until Ctrl-C / SIGTERM
        finally:
            await runtime.engine.stop()
            await runtime.gateway.close()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:  # pragma: no cover
        console.print("\n[yellow]Shutdown requested[/]")


# ---------------------------------------------------------------------------
# demo (dashboard with synthetic live activity — no network)
# ---------------------------------------------------------------------------


@app.command()
def demo(
    host: Annotated[str, typer.Option(help="API bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="API bind port")] = 8000,
) -> None:
    """Serve the dashboard with SYNTHETIC live activity to check every panel.

    No exchange, no network: seeds a portfolio with closed trades, open positions
    and an equity curve, then keeps generating trades/price moves so the dashboard
    (equity curve, PnL, positions, closed trades, risk, strategy performance) all
    populate and update live over the WebSocket. Purely for verifying the UI.
    """
    import random
    from decimal import Decimal
    from types import SimpleNamespace

    import uvicorn

    from quantbot.api.app import create_app
    from quantbot.api.dependencies import AppState
    from quantbot.core.constants import EventType, ExitReason, Side, Timeframe
    from quantbot.core.events import Event, EventBus
    from quantbot.core.models import Candle  # noqa: F401 - ensure models import cleanly
    from quantbot.portfolio.manager import PortfolioManager
    from quantbot.portfolio.performance import PerformanceTracker
    from quantbot.risk.engine import RiskEngine
    from quantbot.strategies.builtin.rsi_strategy import RSIStrategy

    _setup()
    settings = get_settings()
    console.print("[bold magenta]QuantBot DEMO[/] — synthetic data, no exchange")

    rng = random.Random(7)
    start_cap = Decimal("10000")
    syms = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    base = {"BTCUSDT": 65000.0, "ETHUSDT": 3200.0, "BNBUSDT": 580.0}

    bus = EventBus()
    pf = PortfolioManager(starting_balance=start_cap)
    risk = RiskEngine(settings.risk, event_bus=bus)
    risk.set_starting_equity(start_cap)
    perf = PerformanceTracker(starting_equity=float(start_cap))

    def _qty(sym: str, price: float) -> Decimal:
        return Decimal(str(round(float(start_cap) * 0.02 / price, 6)))

    def _open(sym: str, price: float) -> None:
        pf.positions.open_position(
            symbol=sym, side=Side.BUY, quantity=_qty(sym, price),
            entry_price=Decimal(str(round(price, 2))), strategy="rsi_dip_buyer",
            stop_loss=Decimal(str(round(price * 0.97, 2))), fee=Decimal("0"),
        )
        pf.update_price(sym, Decimal(str(round(price, 2))))

    def _close(sym: str, price: float) -> None:
        pf.update_price(sym, Decimal(str(round(price, 2))))
        win = price >= float(pf.positions.get(sym).entry_price)
        trade = pf.positions.close_position(
            sym, exit_price=Decimal(str(round(price, 2))),
            reason=ExitReason.TAKE_PROFIT if win else ExitReason.STOP_LOSS, fee=Decimal("0"),
        )
        if trade is not None:
            pf.apply_trade(trade)
            perf.add_trade(trade)
            risk.limits.record_trade_pnl(trade.net_pnl)

    # Seed ~25 closed trades (slightly positive bias) + an equity curve.
    for _ in range(25):
        sym = rng.choice(syms)
        entry = base[sym] * (1 + rng.uniform(-0.015, 0.015))
        _open(sym, entry)
        _close(sym, entry * (1 + rng.uniform(-0.03, 0.05)))
        risk.update_equity(pf.equity())
        pf.snapshot()
    # Leave two positions open so the Open Positions / unrealized panels fill.
    _open("BTCUSDT", base["BTCUSDT"])
    pf.update_price("BTCUSDT", Decimal(str(round(base["BTCUSDT"] * 1.012, 2))))
    _open("ETHUSDT", base["ETHUSDT"])
    pf.update_price("ETHUSDT", Decimal(str(round(base["ETHUSDT"] * 0.994, 2))))
    pf.snapshot()

    strat = RSIStrategy(
        symbols=syms, timeframes=[Timeframe.M5, Timeframe.M15],
        params={"period": 14, "oversold": 35, "overbought": 70},
    )
    state = AppState(
        settings=settings, portfolio=pf, risk_engine=risk, performance=perf,
        trading_engine=SimpleNamespace(running=True), strategies=[strat],
    )
    application = create_app(settings=settings, state=state, event_bus=bus)

    async def _live_activity() -> None:
        while True:
            await asyncio.sleep(2.5)
            for p in list(pf.positions.all_open()):
                cur = float(pf.price_of(p.symbol) or p.entry_price)
                pf.update_price(p.symbol, Decimal(str(round(cur * (1 + rng.uniform(-0.004, 0.005)), 2))))
            if rng.random() < 0.5 and pf.positions.all_open():
                p = rng.choice(list(pf.positions.all_open()))
                _close(p.symbol, float(pf.price_of(p.symbol) or p.entry_price))
                await bus.publish(Event(EventType.TRADE_CLOSED, payload={"symbol": p.symbol}, source="demo"))
            while len(pf.positions.all_open()) < 2:
                sym = rng.choice(syms)
                if pf.positions.get(sym) and pf.positions.get(sym).is_open:
                    break
                _open(sym, base[sym] * (1 + rng.uniform(-0.01, 0.01)))
                await bus.publish(Event(EventType.TRADE_OPENED, payload={"symbol": sym}, source="demo"))
            risk.update_equity(pf.equity())
            pf.snapshot()
            await bus.publish(Event(EventType.TICKER_UPDATE, payload={"equity": float(pf.equity())}, source="demo"))

    async def _serve() -> None:
        config = uvicorn.Config(application, host=host, port=port, log_level=settings.log_level.lower())
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())
        activity_task = asyncio.create_task(_live_activity())
        console.print(f"[green]Demo dashboard on[/] http://{host}:{port}  (point the UI at it)")
        try:
            await server_task
        finally:
            activity_task.cancel()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:  # pragma: no cover
        console.print("\n[yellow]Demo stopped[/]")


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
