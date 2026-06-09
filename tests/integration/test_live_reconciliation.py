"""Exchange reconciliation: a fired stop or a remotely-closed position must be
reflected in the local books WITHOUT placing a new order — so the bot never
manages a phantom position once it's live.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import AggregatorSettings, BacktestSettings, RiskSettings, Settings
from quantbot.core.constants import OrderStatus, Side, SizingMethod, Timeframe
from quantbot.core.events import EventBus
from quantbot.data.market_data import MarketDataService
from quantbot.engine.paper_broker import PaperTradingBroker
from quantbot.engine.trading_engine import TradingEngine
from quantbot.exchanges.base import OrderUpdate
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine
from quantbot.strategies.aggregator import SignalAggregator

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


def _engine():
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
        max_exposure_per_coin=Decimal("1.0"), max_portfolio_exposure=Decimal("1.0"),
        default_stop_loss_pct=Decimal("0.10"), trailing_stop_pct=Decimal("0.0"),
        break_even_trigger_pct=Decimal("0.0"), take_profit_levels=[],
        max_correlation=Decimal("1.0"), circuit_breaker_losses=99,
        emergency_stop_enabled=False,
    )
    bus = EventBus()
    broker = PaperTradingBroker(MockGateway(), starting_balance=Decimal("10000"),
                               slippage=Decimal("0"), commission=Decimal("0"))
    placed: list = []
    original = broker.create_order

    async def spy(req):
        placed.append(req)
        return await original(req)

    broker.create_order = spy  # type: ignore[method-assign]
    portfolio = PortfolioManager(starting_balance=Decimal("10000"))
    risk = RiskEngine(s.risk, event_bus=bus)
    risk.set_starting_equity(Decimal("10000"))
    executor = OrderExecutor(broker, risk, portfolio, event_bus=bus, commission_rate=Decimal("0"))
    market_data = MarketDataService(broker, event_bus=bus)
    engine = TradingEngine(
        settings=s, gateway=broker, market_data=market_data, strategies=[],
        aggregator=SignalAggregator(s.aggregator), risk_engine=risk, portfolio=portfolio,
        executor=executor, event_bus=bus,
    )
    return engine, portfolio, placed


def _open_long(portfolio):
    portfolio.positions.open_position(
        symbol="BTCUSDT", side=Side.BUY, quantity=Decimal("1"), entry_price=Decimal("100"),
        stop_loss=Decimal("90"),
    )
    portfolio.update_price("BTCUSDT", Decimal("90"))


async def test_fired_stop_user_event_closes_position_without_new_order() -> None:
    engine, portfolio, placed = _engine()
    _open_long(portfolio)
    portfolio.positions.get("BTCUSDT").meta["stop_order_id"] = "stop123"

    # The exchange reports the resting stop filled at 90.
    update = OrderUpdate(
        client_order_id="stop123", exchange_order_id="e1", symbol="BTCUSDT",
        status=OrderStatus.FILLED, filled_qty=Decimal("1"), fill_price=Decimal("90"),
        commission=Decimal("0"), side=Side.SELL,
    )
    await engine._on_order_update(update)

    assert not portfolio.positions.has_position("BTCUSDT"), "position must be closed in the books"
    assert float(portfolio.realized_pnl) == pytest.approx(-10.0, abs=1e-6)  # (90-100)*1
    assert placed == [], "reconciling an exchange-side fill must place NO new order"


async def test_reconcile_on_start_closes_a_remotely_gone_position() -> None:
    engine, portfolio, placed = _engine()
    _open_long(portfolio)  # local says open; MockGateway.get_positions() returns []

    await engine._reconcile_with_exchange()

    assert not portfolio.positions.has_position("BTCUSDT"), "stale local position must be closed"
    assert placed == [], "reconciliation must not place orders"
