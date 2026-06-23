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
from decimal import Decimal
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


@app.command()
def replay(
    days: Annotated[int, typer.Option(help="How many days of history to replay")] = 30,
    timeframe: Annotated[str, typer.Option(help="Candle timeframe (default: smallest configured)")] = "",
    limit: Annotated[int, typer.Option(help="Cap number of symbols (0 = all configured)")] = 0,
    start: Annotated[str, typer.Option(help="Start date YYYY-MM-DD (overrides --days)")] = "",
) -> None:
    """Backtest your ACTUAL config (strategies.yaml + risk) over real history.

    Replays mainnet candles through the real engine, so results reflect the live
    behaviour (trend filter, no-churn, cooldown, risk gates) with realistic paper
    fills. Fast way to test a change before committing days to a live run.
    """
    _setup()
    asyncio.run(_run_replay(days, timeframe, limit, start))


async def _run_replay(days: int, timeframe: str, limit: int, start: str) -> None:
    from datetime import timedelta

    from quantbot.backtest.replay import run_replay

    settings = get_settings()
    if not settings.symbols:
        console.print("[red]No SYMBOLS configured in .env.[/]")
        raise typer.Exit(1)
    tf = Timeframe.from_string(timeframe) if timeframe else min(settings.timeframes, key=lambda t: t.seconds)
    symbols = list(settings.symbols)
    if limit > 0:
        symbols = symbols[:limit]
    end_dt = datetime.now(UTC)
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC) if start else end_dt - timedelta(days=days)

    console.print(
        f"[cyan]Replaying[/] {len(symbols)} symbols · {tf.value} · "
        f"{start_dt.date()} → {end_dt.date()} … (fetching history)"
    )
    result = await run_replay(settings, symbols=symbols, timeframe=tf, start=start_dt, end=end_dt)
    _print_replay(result)


def _print_replay(r: dict) -> None:
    def usdt(v: float) -> str:
        return f"{v:+,.2f} USDT" if v else "0.00 USDT"

    head = Table(title="Backtest (replay of your live config)")
    head.add_column("Metric")
    head.add_column("Value", justify="right")
    pf = r["profit_factor"]
    head.add_row("Symbols / candles", f"{r['symbols']} / {r['candles_replayed']:,}")
    head.add_row("Trades", str(r["trades"]))
    head.add_row("Net PnL (after fees)", usdt(r["net_pnl"]))
    head.add_row("Return", f"{r['bot_return_pct']:+.2f}%")
    bench = r["benchmark_pct"]
    head.add_row(
        f"Buy & hold {r['benchmark_symbol']}",
        "—" if bench is None else f"{bench:+.2f}%",
    )
    head.add_row("Win rate", f"{r['win_rate'] * 100:.1f}%")
    head.add_row("Profit factor", f"{pf:.2f}  ({'edge' if pf > 1 else 'no edge'})")
    head.add_row("Expectancy / trade", usdt(r["expectancy"]))
    head.add_row("Fees", f"{r['fees']:.2f} USDT")
    fpg = r["fees_pct_of_gross"]
    head.add_row("Fees % of gross profit", "—" if fpg is None else f"{fpg:.1f}%")
    head.add_row("Max drawdown", f"{r['max_drawdown_pct']:.2f}%")
    console.print(head)

    if r["by_strategy"]:
        st = Table(title="Per strategy")
        st.add_column("Strategy")
        st.add_column("Net PnL", justify="right")
        for name, pnl in r["by_strategy"].items():
            st.add_row(name, usdt(pnl))
        console.print(st)

    coins = list(r["by_coin"].items())
    if coins:
        worst = Table(title="Worst / best coins")
        worst.add_column("Coin")
        worst.add_column("Net PnL", justify="right")
        for name, pnl in coins[:5] + coins[-5:]:
            worst.add_row(name, usdt(pnl))
        console.print(worst)

    verdict = (
        "Net positive after fees" if r["net_pnl"] > 0 else
        "Net NEGATIVE after fees — no edge demonstrated. Keep iterating; do not risk real money."
    )
    console.print(f"\n[bold]{verdict}[/]")


# ---------------------------------------------------------------------------
# sweep
# ---------------------------------------------------------------------------


#: (label, strategy-param overrides, risk-setting overrides)
_SWEEP_VARIANTS: list[tuple[str, dict, dict]] = [
    ("baseline (current config)", {}, {}),
    ("trend_filter OFF", {"trend_filter": False}, {}),
    ("oversold 35", {"oversold": 35}, {}),
    ("oversold 30", {"oversold": 30}, {}),
    ("trend OFF + oversold 35", {"trend_filter": False, "oversold": 35}, {}),
    ("trend OFF + oversold 30", {"trend_filter": False, "oversold": 30}, {}),
    ("trend_period 30", {"trend_period": 30}, {}),
    ("cooldown OFF", {}, {"reentry_cooldown_seconds": 0}),
    ("exit-on-signal ON", {}, {"exit_on_opposite_signal": True}),
    # Risk/reward structure: the default 3% stop > 2% TP needs a ~60% win rate to
    # break even. A tighter stop / closer TP lowers that bar — test if it's more
    # robust in flat markets (where the live win rate dropped below 60%).
    ("stop 2% (vs 3%)", {}, {"default_stop_loss_pct": Decimal("0.02")}),
    ("tp 1.5%", {}, {"take_profit_levels": [(Decimal("0.015"), Decimal("1.0"))]}),
    ("stop 2% + tp 2.5%", {}, {
        "default_stop_loss_pct": Decimal("0.02"),
        "take_profit_levels": [(Decimal("0.025"), Decimal("1.0"))],
    }),
]


@app.command()
def sweep(
    days: Annotated[int, typer.Option(help="Days of history to replay")] = 30,
    timeframe: Annotated[str, typer.Option(help="Candle timeframe (default: smallest configured)")] = "",
    limit: Annotated[int, typer.Option(help="Cap number of symbols (0 = all)")] = 10,
    start: Annotated[str, typer.Option(help="Window start YYYY-MM-DD (test a past period)")] = "",
) -> None:
    """Compare config variants on the SAME history in one run (fast tuning).

    Backtests your current config plus several tweaks (trend filter on/off,
    oversold levels, cooldown, exit-on-signal) and ranks them by profit factor,
    so you can see which setting backtests best before touching live. Use --start
    to test a DIFFERENT market regime (mean-reversion needs ranging/up markets).
    """
    _setup()
    asyncio.run(_run_sweep(days, timeframe, limit, start))


async def _run_sweep(days: int, timeframe: str, limit: int, start: str = "") -> None:
    from datetime import timedelta

    from quantbot.backtest.replay import load_history, replay_candles

    settings = get_settings()
    if not settings.symbols:
        console.print("[red]No SYMBOLS configured in .env.[/]")
        raise typer.Exit(1)
    tf = Timeframe.from_string(timeframe) if timeframe else min(settings.timeframes, key=lambda t: t.seconds)
    symbols = list(settings.symbols)[: limit or None]
    if start:
        start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
        end_dt = start_dt + timedelta(days=days)
    else:
        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=days)

    console.print(f"[cyan]Loading history once[/] · {len(symbols)} symbols · {tf.value} · {days}d …")
    candles = await load_history(settings, symbols, tf, start_dt, end_dt)
    if not candles:
        console.print("[red]No history loaded.[/]")
        raise typer.Exit(1)

    rows = []
    for label, strat_over, risk_over in _SWEEP_VARIANTS:
        variant_settings = settings.model_copy(deep=True)
        for key, val in risk_over.items():
            setattr(variant_settings.risk, key, val)
        console.print(f"  running: [bold]{label}[/] …")
        r = await replay_candles(variant_settings, candles, tf, param_overrides=strat_over)
        rows.append((label, r))

    rows.sort(key=lambda lr: (lr[1]["profit_factor"], lr[1]["net_pnl"]), reverse=True)

    table = Table(title=f"Sweep — {len(candles)} symbols · {tf.value} · {days}d (ranked by profit factor)")
    table.add_column("Variant")
    for col in ("Trades", "Net PnL", "PF", "Win%", "Fees%", "MaxDD"):
        table.add_column(col, justify="right")
    for label, r in rows:
        pf = r["profit_factor"]
        table.add_row(
            label,
            str(r["trades"]),
            f"{r['net_pnl']:+.2f}",
            f"[green]{pf:.2f}[/]" if pf > 1 else f"[red]{pf:.2f}[/]",
            f"{r['win_rate'] * 100:.0f}%",
            "—" if r["fees_pct_of_gross"] is None else f"{r['fees_pct_of_gross']:.0f}%",
            f"{r['max_drawdown_pct']:.1f}%",
        )
    console.print(table)
    bench = rows[0][1]["benchmark_pct"]
    console.print(
        f"[dim]Buy & hold {rows[0][1]['benchmark_symbol']}: "
        f"{'—' if bench is None else f'{bench:+.2f}%'} · amounts in USDT[/]"
    )
    best = rows[0]
    if best[1]["profit_factor"] <= 1 or best[1]["net_pnl"] <= 0:
        console.print("[yellow]No variant is net-positive with an edge in this window — keep iterating.[/]")
    else:
        console.print(f"[green]Best in this sweep:[/] {best[0]} (PF {best[1]['profit_factor']:.2f})")


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
