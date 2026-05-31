"""Oracle test: the BacktestEngine must execute signals faithfully.

Given known signals on known bars with zero costs, the engine's realised equity
must equal a by-hand calculation. Guards the execution path (sizing, fills, PnL
accounting) against silent regressions, independent of any indicator logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantbot.backtest.engine import BacktestEngine
from quantbot.core.config import (
    AggregatorSettings,
    BacktestSettings,
    RiskSettings,
    Settings,
)
from quantbot.core.constants import Side, SignalType, SizingMethod, Timeframe
from quantbot.core.models import Candle
from quantbot.strategies.base import BaseStrategy
from quantbot.strategies.registry import register_strategy

pytestmark = pytest.mark.integration


@register_strategy
class _OracleBuy25Sell30(BaseStrategy):
    name = "OracleBuy25Sell30"

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return 2

    async def on_candle(self, ctx):
        i = ctx.length - 1
        if i == 25:
            return self.make_signal(ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=1.0)
        if i == 30:
            return self.make_signal(ctx, Side.SELL, signal_type=SignalType.EXIT, strength=1.0)
        return None


def _candles() -> list[Candle]:
    prices = [100.0] * 25 + [110.0, 120.0, 130.0, 140.0, 150.0] + [140.0, 130.0, 120.0]
    out = []
    for i, p in enumerate(prices):
        ot = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i)
        pd = Decimal(str(p))
        out.append(Candle(symbol="TESTUSDT", timeframe=Timeframe.D1, open_time=ot,
                          close_time=ot + timedelta(days=1), open=pd, high=pd, low=pd, close=pd,
                          volume=Decimal("1000")))
    return out


def _settings() -> Settings:
    s = Settings(_env_file=None)
    s.timeframes = [Timeframe.D1]
    s.symbols = ["TESTUSDT"]
    s.backtest = BacktestSettings(
        initial_capital=Decimal("10000"), commission=Decimal("0.0"),
        slippage=Decimal("0.0"), spread=Decimal("0.0"),
    )
    s.risk = RiskSettings(
        sizing_method=SizingMethod.FIXED, risk_per_trade=Decimal("0.10"),
        max_exposure_per_coin=Decimal("1.0"), max_portfolio_exposure=Decimal("1.0"),
        default_stop_loss_pct=Decimal("0.50"), trailing_stop_pct=Decimal("0.0"),
        break_even_trigger_pct=Decimal("0.0"), take_profit_levels=[],
        max_correlation=Decimal("1.0"), circuit_breaker_losses=99,
    )
    s.aggregator = AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=999999)
    return s


def test_engine_executes_signals_exactly() -> None:
    strat = _OracleBuy25Sell30(symbols=["TESTUSDT"], timeframes=[Timeframe.D1])
    result = BacktestEngine(
        settings=_settings(), strategies=[strat], warmup=20, allow_short=False
    ).run(_candles())

    expected_final = 10000.0 / 110.0 * 140.0  # full deploy at 110, sell at 140
    assert len(result.trades) == 1
    assert result.trades[0].side.value == "long"
    assert float(result.trades[0].entry_price) == pytest.approx(110.0)
    assert float(result.trades[0].exit_price) == pytest.approx(140.0)
    assert result.final_equity == pytest.approx(expected_final, abs=1.0)
    net = sum(float(t.net_pnl) for t in result.trades)
    assert result.final_equity == pytest.approx(result.initial_capital + net, abs=1e-3)
