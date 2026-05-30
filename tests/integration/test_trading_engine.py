"""Integration test: the live engine with a paper broker (entry + stop exit)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.constants import Side, Timeframe
from quantbot.core.events import EventBus
from quantbot.data.market_data import MarketDataService
from quantbot.engine.paper_broker import PaperTradingBroker
from quantbot.engine.trading_engine import TradingEngine
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine
from quantbot.strategies.aggregator import SignalAggregator
from quantbot.strategies.base import BaseStrategy

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


class _AlwaysBuyOnce(BaseStrategy):
    name = "AlwaysBuyOnce"

    async def on_candle(self, ctx):
        if ctx.length >= 3 and not self.state.get("done"):
            self.state["done"] = True
            return self.make_signal(ctx, Side.BUY, strength=0.9, reason="test")
        return None


async def test_engine_opens_and_stops_out(settings, make_candle) -> None:
    bus = EventBus()
    broker = PaperTradingBroker(
        MockGateway(), starting_balance=Decimal("10000"),
        slippage=Decimal("0"), commission=Decimal("0"),
    )
    portfolio = PortfolioManager(starting_balance=Decimal("10000"))
    risk = RiskEngine(settings.risk, event_bus=bus)
    risk.set_starting_equity(Decimal("10000"))
    aggregator = SignalAggregator(settings.aggregator)
    executor = OrderExecutor(broker, risk, portfolio, event_bus=bus, commission_rate=Decimal("0"))
    market_data = MarketDataService(broker, event_bus=bus)
    strategy = _AlwaysBuyOnce(symbols=["BTCUSDT"], timeframes=[Timeframe.H1])

    engine = TradingEngine(
        settings=settings, gateway=broker, market_data=market_data,
        strategies=[strategy], aggregator=aggregator, risk_engine=risk,
        portfolio=portfolio, executor=executor, event_bus=bus,
    )

    series = market_data.series("BTCUSDT", Timeframe.H1)
    for i, price in enumerate([100, 101, 102, 103]):
        candle = make_candle(i, price)
        series.append(candle)
        broker.feed_price("BTCUSDT", candle.close)
        await engine.process_candle(candle)

    assert portfolio.positions.has_position("BTCUSDT")

    crash = make_candle(5, 90)
    series.append(crash)
    await engine.process_candle(crash)

    assert not portfolio.positions.has_position("BTCUSDT")
    assert portfolio.realized_pnl < 0
