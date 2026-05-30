#!/usr/bin/env python3
"""Live Binance **testnet** end-to-end verification.

Run this on a machine with outbound network access and testnet API keys to verify
the full stack against the real testnet before paper/live trading. It is staged:

    Stage 1  Connectivity   — ping, server time, clock drift
    Stage 2  Market data    — symbol info, klines, ticker, order book
    Stage 3  Account (auth) — signed balance request (verifies HMAC end-to-end)
    Stage 4  WebSocket      — live kline/ticker stream for a few seconds
    Stage 5  Orders         — place + cancel a tiny far-from-market limit order
                              (only with --order; never fills, never on mainnet)
    Stage 6  Paper run      — a short live-price paper-trading loop through the
                              real TradingEngine (only with --paper)

Setup:
    1. Create SPOT testnet keys at https://testnet.binance.vision/
       (enable Reading + Spot Trading only — never Withdrawals).
    2. In .env set:
         BINANCE__TESTNET=true
         BINANCE__MARKET=spot
         BINANCE__API_KEY=...
         BINANCE__API_SECRET=...
    3. Run:
         python scripts/test_testnet.py                 # stages 1-4
         python scripts/test_testnet.py --order          # + stage 5
         python scripts/test_testnet.py --paper           # + stage 6
         python scripts/test_testnet.py --order --paper   # everything
         python scripts/test_testnet.py --duration 30      # longer WS/paper window

Exit code 0 = all checks passed, 1 = a check failed, 2 = misconfigured.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from decimal import Decimal

from quantbot.core.config import get_settings
from quantbot.core.constants import OrderType, Side, Timeframe, TradingMode
from quantbot.core.utils import to_millis, utcnow
from quantbot.exchanges.base import OrderRequest
from quantbot.exchanges.factory import create_gateway


class _Report:
    """Collects staged check results and prints a final summary."""

    def __init__(self) -> None:
        self._checks: list[tuple[str, str, bool]] = []
        self._stage = ""

    def stage(self, name: str) -> None:
        self._stage = name
        print(f"\n--- {name} ---")

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        self._checks.append((self._stage, label, ok))
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {label}" + (f"  ({detail})" if detail else ""))

    def note(self, text: str) -> None:
        print(f"        {text}")

    def summary(self) -> int:
        total = len(self._checks)
        passed = sum(1 for _, _, ok in self._checks if ok)
        print("\n" + "=" * 60)
        print(f"RESULT: {passed}/{total} checks passed")
        print("=" * 60)
        return 0 if passed == total and total > 0 else 1


async def _stage_connectivity(gateway, report: _Report) -> None:
    report.stage("Stage 1 — Connectivity")
    latency = await gateway.ping()
    report.check("ping reachable", latency >= 0, f"{latency * 1000:.0f} ms")
    server_time = await gateway.server_time()
    drift_ms = abs(to_millis(server_time) - to_millis(utcnow()))
    report.check("server time fetched", True, server_time.isoformat())
    report.check("clock drift < 2000 ms", drift_ms < 2000, f"{drift_ms} ms")
    if drift_ms >= 2000:
        report.note("WARNING: large clock drift can cause signed-request rejections; sync NTP.")


async def _stage_market_data(gateway, symbol: str, report: _Report) -> None:
    report.stage("Stage 2 — Market data")
    info = await gateway.get_symbol_info(symbol)
    report.check(f"symbol info {symbol}", info.symbol == symbol,
                 f"tick={info.tick_size} step={info.step_size} minNotional={info.min_notional}")
    candles = await gateway.get_klines(symbol, Timeframe.M1, limit=20)
    report.check("klines fetched", len(candles) > 0, f"{len(candles)} x 1m")
    monotonic = all(candles[i].open_time < candles[i + 1].open_time for i in range(len(candles) - 1))
    report.check("klines time-ordered", monotonic)
    ticker = await gateway.get_ticker(symbol)
    report.check("ticker fetched", ticker.last_price > 0, f"last={ticker.last_price}")
    book = await gateway.get_order_book(symbol, depth=5)
    spread_ok = book.best_bid is not None and book.best_ask is not None and book.best_ask >= book.best_bid
    report.check("order book sane (ask>=bid)", spread_ok,
                 f"bid={book.best_bid} ask={book.best_ask}")


async def _stage_account(gateway, quote: str, report: _Report) -> None:
    report.stage("Stage 3 — Account (signed request)")
    account = await gateway.get_account()
    report.check("signed account request accepted", True,
                 "HMAC signature accepted by exchange")
    bal = account.balance_of(quote)
    report.check(f"{quote} balance readable", True, f"free={bal.free} locked={bal.locked}")
    if bal.free <= 0:
        report.note(f"NOTE: zero {quote} balance — use the testnet faucet to fund the account.")


async def _stage_websocket(gateway, symbol: str, duration: float, report: _Report) -> None:
    report.stage("Stage 4 — WebSocket stream")
    ws = getattr(gateway, "_ws", None)
    if ws is None:
        report.check("websocket manager present", False, "no WS manager on gateway")
        return
    connected = await ws.wait_connected(timeout=10)
    report.check("websocket connected", connected)
    if not connected:
        return

    received = {"klines": 0, "tickers": 0}

    async def consume_klines() -> None:
        async for _candle in gateway.stream_klines(symbol, Timeframe.M1):
            received["klines"] += 1

    async def consume_tickers() -> None:
        async for _ticker in gateway.stream_tickers([symbol]):
            received["tickers"] += 1

    tasks = [asyncio.create_task(consume_klines()), asyncio.create_task(consume_tickers())]
    report.note(f"listening for {duration:.0f}s …")
    await asyncio.sleep(duration)
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    # Tickers update sub-second; closed 1m klines are rare in a short window.
    report.check("ticker stream delivering", received["tickers"] > 0,
                 f"{received['tickers']} ticker updates")
    report.note(f"closed 1m klines during window: {received['klines']} "
                "(0 is normal for a short run)")


async def _stage_orders(gateway, symbol: str, report: _Report) -> None:
    report.stage("Stage 5 — Order placement (place + cancel)")
    info = await gateway.get_symbol_info(symbol)
    ticker = await gateway.get_ticker(symbol)
    far_price = info.round_price(ticker.last_price * Decimal("0.5"))  # 50% below market
    min_qty = info.min_qty if info.min_qty > 0 else Decimal("0")
    notional_qty = (info.min_notional / far_price * Decimal("1.2")) if info.min_notional > 0 else Decimal("0")
    qty = info.round_qty(max(min_qty, notional_qty, info.step_size))
    report.note(f"placing BUY LIMIT {qty} @ {far_price} (far below market, will not fill)")
    order = await gateway.create_order(
        OrderRequest(symbol=symbol, side=Side.BUY, type=OrderType.LIMIT, quantity=qty, price=far_price)
    )
    report.check("limit order placed", order.exchange_order_id is not None,
                 f"id={order.exchange_order_id} status={order.status.value}")
    # Confirm it is visible as an open order.
    open_orders = await gateway.get_open_orders(symbol)
    report.check("order appears in open orders", any(
        o.exchange_order_id == order.exchange_order_id for o in open_orders))
    cancelled = await gateway.cancel_order(symbol, order_id=order.exchange_order_id)
    report.check("order cancelled", cancelled.status.value in ("canceled", "filled"),
                 f"status={cancelled.status.value}")


async def _stage_paper(gateway, settings, symbol: str, duration: float, report: _Report) -> None:
    report.stage("Stage 6 — Paper run on live testnet prices")
    from quantbot.core.events import EventBus
    from quantbot.data.market_data import MarketDataService
    from quantbot.engine.paper_broker import PaperTradingBroker
    from quantbot.engine.trading_engine import TradingEngine
    from quantbot.execution.executor import OrderExecutor
    from quantbot.portfolio.manager import PortfolioManager
    from quantbot.risk.engine import RiskEngine
    from quantbot.strategies.aggregator import SignalAggregator
    from quantbot.strategies.registry import get_registry

    bus = EventBus()
    broker = PaperTradingBroker(
        gateway, starting_balance=settings.backtest.initial_capital,
        quote_asset=settings.quote_asset, slippage=settings.backtest.slippage,
        commission=settings.backtest.commission,
    )
    portfolio = PortfolioManager(
        starting_balance=settings.backtest.initial_capital, quote_asset=settings.quote_asset
    )
    risk = RiskEngine(settings.risk, event_bus=bus)
    risk.set_starting_equity(settings.backtest.initial_capital)
    aggregator = SignalAggregator(settings.aggregator)
    executor = OrderExecutor(
        broker, risk, portfolio, event_bus=bus, commission_rate=settings.backtest.commission
    )
    market_data = MarketDataService(broker, event_bus=bus)
    registry = get_registry()
    registry.load_builtins()
    strategy = registry.create(
        "EMACrossoverStrategy", symbols=[symbol], timeframes=[Timeframe.M1],
        params={"fast_period": 5, "slow_period": 13},
    )
    engine = TradingEngine(
        settings=settings, gateway=broker, market_data=market_data, strategies=[strategy],
        aggregator=aggregator, risk_engine=risk, portfolio=portfolio, executor=executor,
        event_bus=bus,
    )

    candles_seen = {"n": 0}

    async def on_candle(event) -> None:
        candles_seen["n"] += 1

    from quantbot.core.constants import EventType
    bus.subscribe(EventType.CANDLE_CLOSED, on_candle)

    # Warm up from REST so strategies have history immediately.
    await market_data.warmup([symbol], [Timeframe.M1])
    report.check("paper engine warmed up", len(market_data.series(symbol, Timeframe.M1)) > 0,
                 f"{len(market_data.series(symbol, Timeframe.M1))} warmup candles")

    await engine.start()
    report.note(f"running live paper loop for {duration:.0f}s …")
    await asyncio.sleep(duration)
    await engine.stop(close_positions=False)

    report.check("engine ran without error", True)
    report.check("equity is finite & positive", portfolio.equity() > 0,
                 f"equity={portfolio.equity():.2f}")
    # Accounting invariant holds regardless of whether trades happened.
    invariant = abs(portfolio.equity() - (portfolio.cash + portfolio.unrealized_pnl()
                    - sum((p.fees_paid for p in portfolio.positions.all_open()), Decimal("0")))) < Decimal("0.01")
    report.check("equity accounting invariant", invariant)
    report.note(f"candle events: {candles_seen['n']}, open positions: {portfolio.positions.open_count}, "
                f"realized PnL: {portfolio.realized_pnl:.2f}")


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.binance.testnet:
        print("REFUSING: BINANCE__TESTNET is not true. Set it to true first.")
        return 2
    if not settings.binance.api_key or not settings.binance.api_secret.get_secret_value():
        print("REFUSING: Binance API key/secret not configured in .env.")
        return 2

    symbol = settings.symbols[0] if settings.symbols else "BTCUSDT"
    report = _Report()
    print("=" * 60)
    print(f"BINANCE TESTNET E2E VERIFICATION — {symbol} "
          f"({settings.binance.market.value}, testnet)")
    print("=" * 60)

    gateway = create_gateway(settings)
    started = time.monotonic()
    await gateway.connect()
    try:
        await _stage_connectivity(gateway, report)
        await _stage_market_data(gateway, symbol, report)
        await _stage_account(gateway, settings.quote_asset, report)
        await _stage_websocket(gateway, symbol, args.duration, report)
        if args.order:
            await _stage_orders(gateway, symbol, report)
        if args.paper:
            # Force paper mode for the engine regardless of .env.
            settings.trading_mode = TradingMode.PAPER
            await _stage_paper(gateway, settings, symbol, args.duration, report)
    finally:
        await gateway.close()

    print(f"\nTotal wall time: {time.monotonic() - started:.1f}s")
    return report.summary()


def main() -> int:
    parser = argparse.ArgumentParser(description="Binance testnet end-to-end verification.")
    parser.add_argument("--order", action="store_true", help="also place + cancel a test order")
    parser.add_argument("--paper", action="store_true", help="also run a short paper loop")
    parser.add_argument("--duration", type=float, default=12.0,
                        help="seconds for the WebSocket/paper windows (default 12)")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:  # pragma: no cover
        print("\nInterrupted.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
