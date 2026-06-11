"""On SPOT, restart reconciliation must NOT close positions we still hold.

get_positions() is always [] on spot, so the generic "stale position" logic would
wrongly close every restored position on restart. Spot positions are verified
against base-asset balances instead.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import AggregatorSettings, BacktestSettings, RiskSettings, Settings
from quantbot.core.constants import MarketType, Side, SizingMethod, Timeframe
from quantbot.core.events import EventBus
from quantbot.core.models import Balance
from quantbot.data.market_data import MarketDataService
from quantbot.engine.trading_engine import TradingEngine
from quantbot.exchanges.base import AccountInfo
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine
from quantbot.strategies.aggregator import SignalAggregator

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


class _SpotGateway(MockGateway):
    market = MarketType.SPOT

    def __init__(self, base_balance: Decimal) -> None:
        super().__init__()
        self._base = base_balance

    async def get_account(self) -> AccountInfo:
        return AccountInfo(
            balances={"BTC": Balance(asset="BTC", free=self._base)},
            total_equity=Decimal("10000"), available_balance=Decimal("10000"),
        )

    async def get_positions(self, symbol=None):  # spot: always empty
        return []


def _engine(base_balance: Decimal):
    s = Settings(_env_file=None)
    s.symbols = ["BTCUSDT"]
    s.timeframes = [Timeframe.H1]
    s.quote_asset = "USDT"
    s.aggregator = AggregatorSettings(min_consensus=1)
    s.backtest = BacktestSettings(initial_capital=Decimal("10000"))
    s.risk = RiskSettings(sizing_method=SizingMethod.RISK)
    bus = EventBus()
    gw = _SpotGateway(base_balance)
    pf = PortfolioManager(starting_balance=Decimal("10000"))
    risk = RiskEngine(s.risk, event_bus=bus)
    ex = OrderExecutor(gw, risk, pf, event_bus=bus)
    md = MarketDataService(gw, event_bus=bus)
    eng = TradingEngine(settings=s, gateway=gw, market_data=md, strategies=[],
                        aggregator=SignalAggregator(s.aggregator), risk_engine=risk,
                        portfolio=pf, executor=ex, event_bus=bus)
    pf.positions.open_position(symbol="BTCUSDT", side=Side.BUY, quantity=Decimal("1"),
                               entry_price=Decimal("65000"), fee=Decimal("0"))
    pf.update_price("BTCUSDT", Decimal("65000"))
    return eng, pf


async def test_spot_reconcile_keeps_position_when_balance_held() -> None:
    eng, pf = _engine(base_balance=Decimal("1"))  # account still holds 1 BTC
    await eng._reconcile_with_exchange()
    assert pf.positions.has_position("BTCUSDT"), "must NOT close a position we still hold"


async def test_spot_reconcile_closes_position_when_balance_gone() -> None:
    eng, pf = _engine(base_balance=Decimal("0"))  # BTC sold elsewhere
    await eng._reconcile_with_exchange()
    assert not pf.positions.has_position("BTCUSDT"), "a genuinely-gone position is closed"
