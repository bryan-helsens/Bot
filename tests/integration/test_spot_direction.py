"""Regression tests for spot vs futures position direction.

Guards against the (fixed) flaw where a 'sell' crossover signal opened a SHORT
position on the spot market — which is impossible on spot and caused the bot to
fight strong up-trends. On spot:
    * a buy with no position  -> open long
    * a sell with no position -> no-op (cannot short)
    * a sell while long       -> close the long (exit)
On futures, sells may open shorts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantbot.backtest.engine import BacktestEngine
from quantbot.core.config import BacktestSettings
from quantbot.core.constants import MarketType, Side, SignalType, Timeframe
from quantbot.core.models import Candle, Signal
from quantbot.strategies.base import BaseStrategy
from quantbot.strategies.registry import register_strategy

pytestmark = pytest.mark.integration


@register_strategy
class _AlternatingSignals(BaseStrategy):
    """Emits buy then sell then buy ... on a fixed cadence (for testing)."""

    name = "AlternatingSignals"
    default_params = {"period": 10}

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return 2

    async def on_candle(self, ctx) -> Signal | None:
        period = int(self.param("period"))
        idx = ctx.length
        if idx % period != 0:
            return None
        # Start with a SELL so that, when flat, a short is attempted first
        # (futures opens it; spot ignores it). Then alternate.
        side = Side.SELL if (idx // period) % 2 == 1 else Side.BUY
        return self.make_signal(ctx, side, signal_type=SignalType.ENTRY, strength=0.9)


def _flat_uptrend(n: int = 300) -> list[Candle]:
    out: list[Candle] = []
    price = 100.0
    for i in range(n):
        price *= 1.003  # steady up-trend
        ot = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i)
        p = Decimal(str(round(price, 2)))
        out.append(Candle(
            symbol="BTCUSDT", timeframe=Timeframe.D1, open_time=ot,
            close_time=ot + timedelta(days=1), open=p, high=p, low=p, close=p,
            volume=Decimal("1000"),
        ))
    return out


def _settings(market: MarketType):
    from quantbot.core.config import Settings
    s = Settings(_env_file=None)
    s.binance.market = market
    s.backtest = BacktestSettings(
        initial_capital=Decimal("10000"), commission=Decimal("0.0"),
        slippage=Decimal("0.0"), spread=Decimal("0.0"),
    )
    s.risk.default_stop_loss_pct = Decimal("0.10")
    s.risk.take_profit_levels = [(Decimal("0.20"), Decimal("1.0"))]
    s.risk.max_correlation = Decimal("1.0")
    s.aggregator.min_consensus = 1
    return s


def test_spot_never_opens_short() -> None:
    strat = _AlternatingSignals(symbols=["BTCUSDT"], timeframes=[Timeframe.D1])
    engine = BacktestEngine(settings=_settings(MarketType.SPOT), strategies=[strat], warmup=20)
    result = engine.run(_flat_uptrend())
    # Every realised trade must be a long on spot.
    assert all(t.side.value == "long" for t in result.trades), \
        f"spot produced non-long trades: {[t.side.value for t in result.trades]}"


def test_futures_may_open_short() -> None:
    strat = _AlternatingSignals(symbols=["BTCUSDT"], timeframes=[Timeframe.D1])
    engine = BacktestEngine(
        settings=_settings(MarketType.FUTURES), strategies=[strat], warmup=20, allow_short=True
    )
    result = engine.run(_flat_uptrend())
    sides = {t.side.value for t in result.trades}
    # With shorting enabled (futures), at least one short must be taken — proving
    # the engine opens shorts on sell signals when permitted (the spot path does
    # not). On a steady up-trend these shorts lose, which is expected.
    assert "short" in sides, f"futures took no shorts: {sides}"


def test_real_strategy_long_only_on_spot() -> None:
    """A standard crossover strategy must not short on spot in a backtest."""
    from quantbot.strategies.registry import get_registry
    registry = get_registry()
    registry.load_builtins()
    strat = registry.create(
        "EMACrossoverStrategy", symbols=["BTCUSDT"], timeframes=[Timeframe.D1],
        params={"fast_period": 5, "slow_period": 15},
    )
    engine = BacktestEngine(settings=_settings(MarketType.SPOT), strategies=[strat], warmup=20)
    result = engine.run(_flat_uptrend())
    assert all(t.side.value == "long" for t in result.trades)
