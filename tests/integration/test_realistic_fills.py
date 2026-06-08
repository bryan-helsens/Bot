"""Guard: a stop-loss must fill at a realistic price, not optimistically at the stop.

On daily candles a market can *gap through* a stop overnight — open far below it.
A backtest that assumes the stop fills exactly at its price books a tiny loss on a
crash that would in reality fill at the (much worse) gapped open. That optimism
once inflated the portfolio backtest from a real loss to a fake +100%, diverging
hard from the live paper-trading path. This test pins the realistic behaviour:
the exit fills at the gapped open, not the stop.
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
class _BuyAt25(BaseStrategy):
    name = "BuyAt25Realistic"

    @property
    def min_candles(self) -> int:  # type: ignore[override]
        return 2

    async def on_candle(self, ctx):
        if ctx.length - 1 == 25:
            return self.make_signal(ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=1.0)
        return None


def _candles_with_gap() -> list[Candle]:
    """Flat at 100 through bar 25, then bar 26 gaps far below the 8% stop (92)."""
    out = []
    for i in range(26):
        p = Decimal("100")
        ot = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i)
        out.append(Candle(symbol="GAPUSDT", timeframe=Timeframe.D1, open_time=ot,
                          close_time=ot + timedelta(days=1), open=p, high=p, low=p, close=p,
                          volume=Decimal("1000")))
    # Bar 26: opens at 80 (gapped 20% below the 92 stop), never trades near the stop.
    ot = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=26)
    out.append(Candle(symbol="GAPUSDT", timeframe=Timeframe.D1, open_time=ot,
                      close_time=ot + timedelta(days=1), open=Decimal("80"), high=Decimal("83"),
                      low=Decimal("78"), close=Decimal("82"), volume=Decimal("1000")))
    return out


def _settings() -> Settings:
    s = Settings(_env_file=None)
    s.timeframes = [Timeframe.D1]
    s.backtest = BacktestSettings(
        initial_capital=Decimal("10000"), commission=Decimal("0.0"),
        slippage=Decimal("0.0"), spread=Decimal("0.0"),
    )
    s.risk = RiskSettings(
        sizing_method=SizingMethod.FIXED, risk_per_trade=Decimal("1.0"),
        max_exposure_per_coin=Decimal("1.0"), max_portfolio_exposure=Decimal("1.0"),
        default_stop_loss_pct=Decimal("0.08"), trailing_stop_pct=Decimal("0.0"),
        break_even_trigger_pct=Decimal("0.0"), take_profit_levels=[],
        max_correlation=Decimal("1.0"), circuit_breaker_losses=99,
    )
    s.aggregator = AggregatorSettings(min_consensus=1, min_strength=0.5, window_seconds=999999)
    return s


def test_stop_fills_at_gapped_open_not_at_stop() -> None:
    strat = _BuyAt25(symbols=["GAPUSDT"], timeframes=[Timeframe.D1])
    result = BacktestEngine(
        settings=_settings(), strategies=[strat], warmup=20, allow_short=False
    ).run(_candles_with_gap())

    assert len(result.trades) == 1
    trade = result.trades[0]
    # Entry at 100 (full deploy), stop at 92, but the bar gapped to open 80.
    assert float(trade.entry_price) == pytest.approx(100.0)
    # Realistic fill is the gapped open (80), NOT the stop (92).
    assert float(trade.exit_price) == pytest.approx(80.0)
    # ~ -20% loss, not the ~ -8% the optimistic fill would have booked.
    assert float(result.final_equity) == pytest.approx(8000.0, abs=5.0)
