#!/usr/bin/env python3
"""Offline paper-trading validation — drives the LIVE engine over a candle replay.

Unlike the backtester, this runs the real :class:`TradingEngine` decision+execution
loop (strategies → aggregator → RiskEngine → OrderExecutor → PaperTradingBroker →
PortfolioManager) candle by candle. Because the exchange here is a
:class:`PaperTradingBroker` wrapping an in-memory gateway, no order touches a real
venue, yet the code path is identical to live paper-trading. Replaying historical
candles through it confirms the live path reproduces the backtest result — the
last check before pointing the same engine at a real testnet feed.

For REAL testnet paper-trading on a machine with exchange access, don't use this
script — set ``TRADING_MODE=paper`` and ``BINANCE__TESTNET=true`` (+ testnet keys)
in ``.env`` and run ``quantbot run``. This script exists because exchange APIs are
unreachable in some sandboxes; it validates the same engine offline.

    python scripts/papertrade_replay.py            # all coins in data/all
    python scripts/papertrade_replay.py btc eth bnb
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# Example config (NOT proven profitable — see docs/REALISTIC_FILLS_REPORT.md). This
# replay exists to confirm the live path reproduces the backtest, not to show profit.
WINNING = {
    "risk_per_trade": Decimal("0.015"), "max_portfolio_exposure": Decimal("0.80"),
    "max_open_trades": 5, "stop": Decimal("0.08"), "target": Decimal("0.06"),
    "trail": Decimal("0.15"), "oversold": 35.0, "overbought": 70.0, "rsi_period": 14,
}


def _load_candles(path: str, symbol: str):
    from quantbot.core.constants import Timeframe
    from quantbot.core.models import Candle

    out = []
    for date_str, close in json.load(open(path)):
        d = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        p = Decimal(str(close))
        out.append(Candle(symbol=symbol, timeframe=Timeframe.D1, open_time=d,
                          close_time=d + timedelta(days=1), open=p, high=p, low=p,
                          close=p, volume=Decimal("100")))
    return out


def _settings():
    from quantbot.core.config import (
        AggregatorSettings, BacktestSettings, RiskSettings, Settings,
    )
    from quantbot.core.constants import MarketType, SizingMethod, Timeframe, TradingMode

    s = Settings(_env_file=None)
    s.binance.market = MarketType.SPOT
    s.trading_mode = TradingMode.PAPER
    s.timeframes = [Timeframe.D1]
    s.risk = RiskSettings(
        sizing_method=SizingMethod.RISK, risk_per_trade=WINNING["risk_per_trade"],
        max_open_trades=WINNING["max_open_trades"], max_exposure_per_coin=Decimal("1.0"),
        max_portfolio_exposure=WINNING["max_portfolio_exposure"],
        default_stop_loss_pct=WINNING["stop"], trailing_stop_pct=WINNING["trail"],
        break_even_trigger_pct=Decimal("0"),
        take_profit_levels=[(WINNING["target"], Decimal("1.0"))],
        max_daily_loss=Decimal("0.95"), max_weekly_loss=Decimal("0.95"),
        max_drawdown=Decimal("0.95"), max_correlation=Decimal("1.0"),
        circuit_breaker_losses=999, emergency_stop_enabled=False,
    )
    s.aggregator = AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=999999)
    s.backtest = BacktestSettings(
        initial_capital=Decimal("10000"), commission=Decimal("0.001"),
        slippage=Decimal("0.0005"), spread=Decimal("0.0002"),
    )
    return s


async def _replay(series: dict[str, list]) -> dict:
    from quantbot.core.constants import Timeframe
    from quantbot.core.events import EventBus
    from quantbot.data.market_data import MarketDataService
    from quantbot.engine.paper_broker import PaperTradingBroker
    from quantbot.engine.trading_engine import TradingEngine
    from quantbot.execution.executor import OrderExecutor
    from quantbot.portfolio.manager import PortfolioManager
    from quantbot.risk.engine import RiskEngine
    from quantbot.strategies.aggregator import SignalAggregator
    from quantbot.strategies.builtin.rsi_strategy import RSIStrategy

    from tests.conftest import MockGateway

    settings = _settings()
    cap = settings.backtest.initial_capital
    bus = EventBus()
    broker = PaperTradingBroker(
        MockGateway(), starting_balance=cap, slippage=settings.backtest.slippage,
        commission=settings.backtest.commission,
    )
    portfolio = PortfolioManager(starting_balance=cap, quote_asset="USDT")
    risk = RiskEngine(settings.risk, event_bus=bus)
    risk.set_starting_equity(cap)
    aggregator = SignalAggregator(settings.aggregator)
    executor = OrderExecutor(broker, risk, portfolio, event_bus=bus,
                             commission_rate=settings.backtest.commission)
    market_data = MarketDataService(broker, event_bus=bus)
    strat = RSIStrategy(symbols=[], timeframes=[Timeframe.D1], params={
        "period": WINNING["rsi_period"], "oversold": WINNING["oversold"],
        "overbought": WINNING["overbought"]})
    engine = TradingEngine(
        settings=settings, gateway=broker, market_data=market_data, strategies=[strat],
        aggregator=aggregator, risk_engine=risk, portfolio=portfolio, executor=executor,
        event_bus=bus,
    )

    # Replay every symbol's candles in global timestamp order so the shared
    # account's caps bind across coins exactly as they would live.
    events = sorted(
        ((c.open_time, sym, c) for sym, candles in series.items() for c in candles),
        key=lambda e: e[0],
    )
    peak = float(cap)
    max_dd = 0.0
    for _, sym, candle in events:
        market_data.series(sym, candle.timeframe).append(candle)
        broker.feed_price(sym, candle.close)
        await engine.process_candle(candle)
        eq = float(portfolio.equity())
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0.0)

    await engine._flatten_all()
    final = float(portfolio.equity())
    return {
        "final_equity": final,
        "return_pct": (final / float(cap) - 1) * 100,
        "realized_pnl": float(portfolio.realized_pnl),
        "max_drawdown_pct": max_dd * 100,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*", help="coin tickers (default: all in data/all)")
    parser.add_argument("--data", default="data/all")
    args = parser.parse_args()

    from quantbot.core.logging import configure_logging
    configure_logging(level="ERROR")

    if args.symbols:
        paths = [os.path.join(args.data, f"{s.lower()}_daily_close.json") for s in args.symbols]
    else:
        paths = sorted(glob.glob(os.path.join(args.data, "*_daily_close.json")))
    series = {}
    for p in paths:
        if os.path.exists(p):
            sym = os.path.basename(p).replace("_daily_close.json", "").upper() + "USDT"
            series[sym] = _load_candles(p, sym)

    print(f"PAPER-TRADING REPLAY (live engine, {len(series)} coins) — winning portfolio config")
    print("=" * 78)
    r = asyncio.run(_replay(series))
    print(f"  final equity : ${r['final_equity']:,.0f}")
    print(f"  return       : {r['return_pct']:+.1f}%")
    print(f"  realized PnL : ${r['realized_pnl']:,.0f}")
    print(f"  max drawdown : {r['max_drawdown_pct']:.0f}%")
    print("\nLive code path exercised end-to-end (PaperTradingBroker). For real testnet")
    print("paper-trading: set TRADING_MODE=paper + BINANCE__TESTNET=true and run `quantbot run`.")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    main()
