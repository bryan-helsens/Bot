"""Position sizing must use a smoothed ATR, not a single bar's high-low range."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantbot.core.config import AggregatorSettings, BacktestSettings, RiskSettings, Settings
from quantbot.core.constants import SizingMethod, Timeframe
from quantbot.core.events import EventBus
from quantbot.core.models import Candle
from quantbot.data.market_data import MarketDataService
from quantbot.engine.paper_broker import PaperTradingBroker
from quantbot.engine.trading_engine import TradingEngine
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine
from quantbot.strategies.aggregator import SignalAggregator

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


def _candle(i: int, *, high: float, low: float, close: float) -> Candle:
    ot = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i)
    return Candle(
        symbol="BTCUSDT", timeframe=Timeframe.H1, open_time=ot,
        close_time=ot + timedelta(hours=1), open=Decimal(str(close)),
        high=Decimal(str(high)), low=Decimal(str(low)), close=Decimal(str(close)),
        volume=Decimal("100"),
    )


def _engine():
    s = Settings(_env_file=None)
    s.symbols = ["BTCUSDT"]
    s.timeframes = [Timeframe.H1]
    s.aggregator = AggregatorSettings(min_consensus=1)
    s.backtest = BacktestSettings(initial_capital=Decimal("10000"))
    s.risk = RiskSettings(sizing_method=SizingMethod.RISK)
    bus = EventBus()
    broker = PaperTradingBroker(MockGateway(), starting_balance=Decimal("10000"))
    pf = PortfolioManager(starting_balance=Decimal("10000"))
    risk = RiskEngine(s.risk, event_bus=bus)
    md = MarketDataService(broker, event_bus=bus)
    ex = OrderExecutor(broker, risk, pf, event_bus=bus)
    return TradingEngine(
        settings=s, gateway=broker, market_data=md, strategies=[],
        aggregator=SignalAggregator(s.aggregator), risk_engine=risk, portfolio=pf,
        executor=ex, event_bus=bus,
    ), md


def test_atr_is_smoothed_not_single_candle_range() -> None:
    engine, md = _engine()
    series = md.series("BTCUSDT", Timeframe.H1)
    # 19 calm bars (range 0.2), then one violent bar (range 20).
    for i in range(19):
        series.append(_candle(i, high=100.1, low=99.9, close=100.0))
    spike = _candle(19, high=110.0, low=90.0, close=100.0)
    series.append(spike)

    atr = engine._atr_for(spike)
    assert atr is not None
    # Smoothed ATR is dominated by the 19 calm bars, so it is FAR below the spike's
    # own 20-wide range — proving it isn't just the single-candle range.
    assert float(spike.range) == pytest.approx(20.0)
    assert 0.2 < float(atr) < 5.0


def test_atr_falls_back_to_range_with_little_history() -> None:
    engine, md = _engine()
    series = md.series("BTCUSDT", Timeframe.H1)
    c = _candle(0, high=101.0, low=99.0, close=100.0)
    series.append(c)
    # Too few bars for ATR(14): fall back to the single-candle range (=2).
    assert float(engine._atr_for(c)) == pytest.approx(2.0)
