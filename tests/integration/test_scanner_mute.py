"""Market scanner produces live per-coin indicator rows, and per-coin mute stops
NEW automated entries while leaving the coin warmed up and visible."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import AggregatorSettings, RiskSettings, Settings
from quantbot.core.constants import SizingMethod, Timeframe
from quantbot.core.events import EventBus
from quantbot.data.market_data import MarketDataService
from quantbot.engine.trading_engine import TradingEngine
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine
from quantbot.strategies.aggregator import SignalAggregator

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


def _engine_with_candles(make_candle):
    candles = {"BTCUSDT": [make_candle(i, 100 + (i % 7), symbol="BTCUSDT", timeframe=Timeframe.M5)
                           for i in range(40)]}
    gateway = MockGateway(candles=candles)
    s = Settings(_env_file=None)
    s.symbols = ["BTCUSDT"]
    s.timeframes = [Timeframe.M5]
    s.aggregator = AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=999999)
    s.risk = RiskSettings(
        sizing_method=SizingMethod.RISK, risk_per_trade=Decimal("0.02"),
        max_open_trades=5, max_exposure_per_coin=Decimal("1.0"),
        max_portfolio_exposure=Decimal("1.0"), default_stop_loss_pct=Decimal("0.10"),
        trailing_stop_pct=Decimal("0.0"), break_even_trigger_pct=Decimal("0.0"),
        take_profit_levels=[], max_correlation=Decimal("1.0"), circuit_breaker_losses=99,
        emergency_stop_enabled=False,
    )
    bus = EventBus()
    portfolio = PortfolioManager(starting_balance=Decimal("10000"))
    risk = RiskEngine(s.risk, event_bus=bus)
    risk.set_starting_equity(Decimal("10000"))
    executor = OrderExecutor(gateway, risk, portfolio, event_bus=bus, commission_rate=Decimal("0"))
    market_data = MarketDataService(gateway, event_bus=bus)
    engine = TradingEngine(
        settings=s, gateway=gateway, market_data=market_data, strategies=[],
        aggregator=SignalAggregator(s.aggregator), risk_engine=risk, portfolio=portfolio,
        executor=executor, event_bus=bus,
    )
    return engine, market_data


async def test_market_scanner_returns_indicator_rows(make_candle) -> None:
    engine, market_data = _engine_with_candles(make_candle)
    await market_data.warmup(["BTCUSDT"], [Timeframe.M5])

    rows = engine.market_scanner()
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "BTCUSDT"
    assert row["rsi"] is not None
    assert row["ema_fast"] is not None and row["ema_slow"] is not None
    assert row["trend"] in {"up", "down"}
    assert row["timeframe"] == "5m"
    assert row["muted"] is False


async def test_mute_toggles_and_is_reflected_in_scanner(make_candle) -> None:
    engine, market_data = _engine_with_candles(make_candle)
    await market_data.warmup(["BTCUSDT"], [Timeframe.M5])

    assert engine.muted_symbols() == []
    engine.mute_symbol("btcusdt")  # case-insensitive
    assert engine.muted_symbols() == ["BTCUSDT"]
    assert engine.market_scanner()[0]["muted"] is True

    engine.unmute_symbol("BTCUSDT")
    assert engine.muted_symbols() == []
