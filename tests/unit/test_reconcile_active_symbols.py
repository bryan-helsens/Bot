"""Reconciliation must only query symbols the exchange actually lists.

A coin configured in SYMBOLS but absent from the (test)net — MATIC/FTM/MKR/RNDR
off the Binance spot testnet — raises -1121 Invalid symbol when queried. Before
the fix one such symbol aborted the WHOLE reconciliation pass
(``reconcile_failed error=Invalid symbol``). Now bad symbols are skipped per
symbol, and the engine only asks about symbols that warmed up.
"""

from __future__ import annotations

import pytest

from quantbot.core.constants import Timeframe
from quantbot.data.market_data import MarketDataService
from quantbot.exchanges.synchronizer import OrderSynchronizer

from tests.conftest import MockGateway

pytestmark = pytest.mark.unit


async def test_fetch_open_orders_skips_invalid_symbol() -> None:
    """One -1121 symbol must not abort the fetch; the rest still resolve."""
    gateway = MockGateway()
    queried: list[str] = []

    async def get_open_orders(symbol: str | None = None):
        queried.append(symbol)
        if symbol == "FTMUSDT":
            raise RuntimeError("Invalid symbol. (-1121)")
        return []

    gateway.get_open_orders = get_open_orders  # type: ignore[method-assign]
    sync = OrderSynchronizer(gateway)

    result = await sync.reconcile([], [], symbols=["BTCUSDT", "FTMUSDT", "ETHUSDT"])

    assert queried == ["BTCUSDT", "FTMUSDT", "ETHUSDT"], "every symbol still attempted"
    assert not result.has_discrepancies, "a skipped bad symbol must not break reconcile"


async def test_active_symbols_excludes_unlisted_coins() -> None:
    """Only coins that returned klines on warmup count as active."""
    gateway = MockGateway()

    async def get_klines(symbol, timeframe, *, limit=500, start_time=None, end_time=None):
        if symbol == "FTMUSDT":
            raise RuntimeError("Invalid symbol. (-1121)")
        return []

    gateway.get_klines = get_klines  # type: ignore[method-assign]
    md = MarketDataService(gateway)

    await md.warmup(["BTCUSDT", "FTMUSDT", "ETHUSDT"], [Timeframe.M5])

    assert md.active_symbols() == ["BTCUSDT", "ETHUSDT"], "unlisted FTM is excluded"
