"""Advanced safety tests for the LIVE/paper execution path.

These guard the invariants that matter when real (testnet/live) money is at stake:
the bot never updates its books without the matching exchange order, accounting
stays consistent, and the risk gate cannot be bypassed. They drive the real
:class:`TradingEngine` through :meth:`process_candle` with a
:class:`PaperTradingBroker`, exactly as live paper-trading runs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import AggregatorSettings, BacktestSettings, RiskSettings, Settings
from quantbot.core.constants import (
    OrderType,
    Side,
    SizingMethod,
    Timeframe,
)
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


class _BuyOnceAt3(BaseStrategy):
    name = "BuyOnceAt3Live"

    async def on_candle(self, ctx):
        if ctx.length >= 3 and not self.state.get("done"):
            self.state["done"] = True
            return self.make_signal(ctx, Side.BUY, strength=0.9, reason="test")
        return None


def _settings(*, take_profit_levels, stop_pct="0.10", max_exposure="1.0", max_open=5) -> Settings:
    s = Settings(_env_file=None)
    s.symbols = ["BTCUSDT"]
    s.timeframes = [Timeframe.H1]
    s.aggregator = AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=999999)
    s.backtest = BacktestSettings(
        initial_capital=Decimal("10000"), commission=Decimal("0.0"),
        slippage=Decimal("0.0"), spread=Decimal("0.0"),
    )
    s.risk = RiskSettings(
        sizing_method=SizingMethod.RISK, risk_per_trade=Decimal("0.02"),
        max_open_trades=max_open, max_exposure_per_coin=Decimal(max_exposure),
        max_portfolio_exposure=Decimal(max_exposure), default_stop_loss_pct=Decimal(stop_pct),
        trailing_stop_pct=Decimal("0.0"), break_even_trigger_pct=Decimal("0.0"),
        take_profit_levels=take_profit_levels, max_daily_loss=Decimal("0.95"),
        max_weekly_loss=Decimal("0.95"), max_drawdown=Decimal("0.95"),
        max_correlation=Decimal("1.0"), circuit_breaker_losses=99,
        emergency_stop_enabled=False,
    )
    return s


def _wire(settings: Settings, strategy: BaseStrategy):
    bus = EventBus()
    broker = PaperTradingBroker(
        MockGateway(), starting_balance=settings.backtest.initial_capital,
        slippage=Decimal("0"), commission=Decimal("0"),
    )
    # Capture every order request that reaches the (paper) exchange.
    placed: list = []
    original = broker.create_order

    async def _spy(request):
        placed.append(request)
        return await original(request)

    broker.create_order = _spy  # type: ignore[method-assign]

    portfolio = PortfolioManager(starting_balance=settings.backtest.initial_capital)
    risk = RiskEngine(settings.risk, event_bus=bus)
    risk.set_starting_equity(Decimal("10000"))
    aggregator = SignalAggregator(settings.aggregator)
    executor = OrderExecutor(broker, risk, portfolio, event_bus=bus, commission_rate=Decimal("0"))
    market_data = MarketDataService(broker, event_bus=bus)
    engine = TradingEngine(
        settings=settings, gateway=broker, market_data=market_data, strategies=[strategy],
        aggregator=aggregator, risk_engine=risk, portfolio=portfolio, executor=executor,
        event_bus=bus,
    )
    return engine, portfolio, broker, placed, market_data


async def _feed(engine, market_data, broker, prices, make_candle):
    series = market_data.series("BTCUSDT", Timeframe.H1)
    for i, price in enumerate(prices):
        candle = make_candle(i, price)
        series.append(candle)
        broker.feed_price("BTCUSDT", candle.close)
        await engine.process_candle(candle)


async def test_partial_take_profit_places_a_real_reduce_order(make_candle) -> None:
    """A partial TP must place a reduce-only sell order, not just edit the books."""
    settings = _settings(take_profit_levels=[(Decimal("0.02"), Decimal("0.5"))])
    strategy = _BuyOnceAt3(symbols=["BTCUSDT"], timeframes=[Timeframe.H1])
    engine, portfolio, broker, placed, market_data = _wire(settings, strategy)

    # Flat at 100 (entry), then +3% (103) triggers the +2% take-profit rung.
    await _feed(engine, market_data, broker, [100, 100, 100, 103], make_candle)

    pos = portfolio.positions.get("BTCUSDT")
    assert pos is not None and pos.is_open, "position should remain open after a 50% reduce"

    entry_qty = Decimal("10000") * Decimal("0.02") / (Decimal("100") * Decimal("0.10"))  # =20
    assert pos.quantity == pytest.approx(entry_qty / 2, abs=1e-6), "remaining ≈ 50% of entry"

    reduce_orders = [
        r for r in placed
        if r.type is OrderType.MARKET and r.side is Side.SELL and r.reduce_only
    ]
    assert len(reduce_orders) == 1, "exactly one real reduce-only sell must reach the exchange"
    assert reduce_orders[0].quantity == pytest.approx(entry_qty / 2, abs=1e-6)


async def test_accounting_invariant_holds_through_partial_then_close(make_candle) -> None:
    """equity == cash + unrealised − open fees at every step, through a partial TP."""
    settings = _settings(take_profit_levels=[(Decimal("0.02"), Decimal("0.5"))])
    strategy = _BuyOnceAt3(symbols=["BTCUSDT"], timeframes=[Timeframe.H1])
    engine, portfolio, broker, _placed, market_data = _wire(settings, strategy)

    await _feed(engine, market_data, broker, [100, 100, 100, 103], make_candle)

    # commission/slippage are zero: entry 20 @100, sell 10 @103 -> realised +30,
    # remaining 10 marked at 103 -> unrealised +30, equity 10060.
    assert float(portfolio.realized_pnl) == pytest.approx(30.0, abs=1e-6)
    invariant = portfolio.equity() - (
        portfolio.cash + portfolio.unrealized_pnl()
        - sum((p.fees_paid for p in portfolio.positions.all_open()), Decimal("0"))
    )
    assert abs(float(invariant)) < 1e-9
    assert float(portfolio.equity()) == pytest.approx(10060.0, abs=1e-6)


async def test_exposure_cap_shrinks_order_to_fit(make_candle) -> None:
    """The risk gate caps an over-sized order down to the exposure limit."""
    # Cap exposure at 5% of equity; the risk-sized notional (~20%) exceeds it, so the
    # engine must ADJUST (shrink) the order rather than over-expose the account.
    settings = _settings(
        take_profit_levels=[(Decimal("0.10"), Decimal("1.0"))], max_exposure="0.05",
    )
    strategy = _BuyOnceAt3(symbols=["BTCUSDT"], timeframes=[Timeframe.H1])
    engine, portfolio, broker, _placed, market_data = _wire(settings, strategy)

    await _feed(engine, market_data, broker, [100, 100, 100, 100], make_candle)

    pos = portfolio.positions.get("BTCUSDT")
    assert pos is not None and pos.is_open
    # Notional must not exceed the 5% cap (current-price valued).
    assert float(pos.notional(Decimal("100"))) <= 0.05 * 10000 + 1e-6


async def test_emergency_stop_blocks_all_orders(make_candle) -> None:
    """With the kill switch active, no signal may place any exchange order."""
    settings = _settings(take_profit_levels=[(Decimal("0.10"), Decimal("1.0"))])
    strategy = _BuyOnceAt3(symbols=["BTCUSDT"], timeframes=[Timeframe.H1])
    engine, portfolio, broker, placed, market_data = _wire(settings, strategy)

    engine._risk.emergency.trigger("test halt")  # activate the global kill switch

    await _feed(engine, market_data, broker, [100, 100, 100, 100], make_candle)

    assert not portfolio.positions.has_position("BTCUSDT"), "no position while halted"
    assert placed == [], "a kill-switched engine must place no exchange orders"
