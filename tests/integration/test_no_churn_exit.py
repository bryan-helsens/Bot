"""By default an opposite signal must NOT close an open position — it rides to
its TP/SL/trailing. Flipping on every signal was the main fee drain. The behaviour
is restored only when RISK__EXIT_ON_OPPOSITE_SIGNAL=true.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.constants import Side, Timeframe
from quantbot.strategies.base import BaseStrategy

from tests.integration.test_live_execution import _feed, _settings, _wire

pytestmark = pytest.mark.integration


class _BuyThenSell(BaseStrategy):
    """Buy on the 3rd candle, then emit a SELL on the 5th (the 'flip')."""

    name = "BuyThenSell"

    async def on_candle(self, ctx):
        if ctx.length == 3 and not self.state.get("bought"):
            self.state["bought"] = True
            return self.make_signal(ctx, Side.BUY, strength=0.9, reason="entry")
        if ctx.length == 5 and not self.state.get("flipped"):
            self.state["flipped"] = True
            return self.make_signal(ctx, Side.SELL, strength=0.9, reason="flip")
        return None


async def test_opposite_signal_does_not_close_by_default(make_candle) -> None:
    settings = _settings(take_profit_levels=[])
    settings.risk.exit_on_opposite_signal = False
    engine, portfolio, _broker, _placed, market_data = _wire(settings, _BuyThenSell())

    await _feed(engine, market_data, _broker, [100, 100, 100, 101, 101], make_candle)

    # The SELL on candle 5 must be ignored — position still open.
    assert portfolio.positions.has_position("BTCUSDT")


async def test_opposite_signal_closes_when_enabled(make_candle) -> None:
    settings = _settings(take_profit_levels=[])
    settings.risk.exit_on_opposite_signal = True
    engine, portfolio, _broker, _placed, market_data = _wire(settings, _BuyThenSell())

    await _feed(engine, market_data, _broker, [100, 100, 100, 101, 101], make_candle)

    # With the flag on, the flip closes the long.
    assert not portfolio.positions.has_position("BTCUSDT")
