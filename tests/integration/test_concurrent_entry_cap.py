"""A burst of candles closing at the same instant must NOT collectively blow past
the max-open-trades / exposure caps. The event bus runs candle handlers
concurrently, so without serialising the entry decision the bot opened far more
positions than configured (seen live: 12-17 open with a cap of 8)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from quantbot.core.constants import Side, Timeframe
from quantbot.strategies.base import BaseStrategy

from tests.integration.test_live_execution import _feed, _settings, _wire
from tests.conftest import MockGateway  # noqa: F401 - kept for parity with siblings

pytestmark = pytest.mark.integration


class _AlwaysBuy(BaseStrategy):
    """Emit a BUY on every candle once warmed up — to hammer the entry path."""

    name = "AlwaysBuy"

    async def on_candle(self, ctx):
        if ctx.length >= 3:
            return self.make_signal(ctx, Side.BUY, strength=0.9, reason="test")
        return None


async def test_concurrent_candles_respect_max_open_cap(make_candle) -> None:
    settings = _settings(take_profit_levels=[], max_open=3, max_exposure="1.0")
    settings.symbols = ["BTCUSDT"]
    engine, portfolio, _broker, _placed, market_data = _wire(settings, _AlwaysBuy())

    # Warm up 5 distinct symbols, each with enough history to signal.
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    candles = {}
    for sym in symbols:
        series = market_data.series(sym, Timeframe.H1)
        cs = [make_candle(i, 100 + i, symbol=sym, timeframe=Timeframe.H1) for i in range(5)]
        for c in cs:
            series.append(c)
        _broker.feed_price(sym, cs[-1].close)
        candles[sym] = cs[-1]

    # Fire all symbols' candles CONCURRENTLY (as the live event bus does).
    await asyncio.gather(*(engine.process_candle(candles[s]) for s in symbols))

    # Hard cap of 3 must hold despite 5 simultaneous buy signals.
    assert portfolio.positions.open_count <= 3, (
        f"opened {portfolio.positions.open_count} positions, cap was 3"
    )
