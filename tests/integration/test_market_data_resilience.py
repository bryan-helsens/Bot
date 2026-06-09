"""A configured symbol the exchange doesn't list must be skipped, not fatal.

When the basket includes meme/low-cap coins that aren't on the testnet, warmup must
skip them (logged) and start consumers only for the symbols that returned data — so
one bad symbol can never crash the whole engine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantbot.core.constants import Timeframe
from quantbot.core.events import EventBus
from quantbot.core.exceptions import InvalidOrderError
from quantbot.core.models import Candle
from quantbot.data.market_data import MarketDataService

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


def _candles(symbol: str, n: int = 30) -> list[Candle]:
    out = []
    for i in range(n):
        ot = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i)
        p = Decimal("100")
        out.append(Candle(symbol=symbol, timeframe=Timeframe.H1, open_time=ot,
                          close_time=ot + timedelta(hours=1), open=p, high=p, low=p,
                          close=p, volume=Decimal("1")))
    return out


class _PartialGateway(MockGateway):
    """Lists BTCUSDT but raises for the unknown BADUSDT (as the testnet would)."""

    async def get_klines(self, symbol, timeframe, *, limit=500, start_time=None, end_time=None):
        if symbol == "BADUSDT":
            raise InvalidOrderError("Invalid symbol", context={"symbol": symbol})
        return await super().get_klines(symbol, timeframe, limit=limit)


async def test_warmup_skips_unlisted_symbol_and_keeps_the_rest() -> None:
    gateway = _PartialGateway({"BTCUSDT": _candles("BTCUSDT")})
    md = MarketDataService(gateway, event_bus=EventBus())

    # Must NOT raise despite BADUSDT being unavailable.
    await md.warmup(["BTCUSDT", "BADUSDT"], [Timeframe.H1])

    assert md._active == [("BTCUSDT", Timeframe.H1)]
    assert len(md.series("BTCUSDT", Timeframe.H1)) == 30
