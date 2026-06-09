"""Futures order placement must use USD-M order types and send reduceOnly.

Spot uses STOP_LOSS and ignores reduce_only; on futures that is invalid and would
leave a protective stop rejected (an unstopped position). These tests pin the
correct futures params without touching the network.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import Settings
from quantbot.core.constants import MarketType, OrderType, Side
from quantbot.core.models import Order, OrderStatus, SymbolInfo
from quantbot.exchanges.base import OrderRequest
from quantbot.exchanges.binance_futures import BinanceFuturesGateway

pytestmark = pytest.mark.unit


@pytest.fixture
def gw(monkeypatch):
    gateway = BinanceFuturesGateway(Settings(_env_file=None))
    captured: dict = {}

    async def fake_symbol_info(symbol):
        return SymbolInfo(
            symbol=symbol, base_asset="BTC", quote_asset="USDT", market=MarketType.FUTURES,
            tick_size=Decimal("0.1"), step_size=Decimal("0.001"),
        )

    async def fake_request(method, path, *, params=None, **kw):
        captured["params"] = params
        return {}

    def fake_parse(data, request=None):
        p = captured["params"]
        return Order(
            client_order_id=p.get("newClientOrderId", "x"), symbol=p["symbol"],
            side=Side(p["side"].lower()), type=request.type if request else OrderType.MARKET,
            quantity=Decimal(p["quantity"]), status=OrderStatus.NEW,
        )

    monkeypatch.setattr(gateway, "get_symbol_info", fake_symbol_info)
    monkeypatch.setattr(gateway, "_request", fake_request)
    monkeypatch.setattr(gateway, "_parse_order", fake_parse)
    gateway._captured = captured  # type: ignore[attr-defined]
    return gateway


async def test_futures_stop_uses_stop_market_and_reduce_only(gw) -> None:
    await gw.create_order(OrderRequest(
        symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_LOSS,
        quantity=Decimal("0.5"), stop_price=Decimal("90"), reduce_only=True,
    ))
    p = gw._captured["params"]
    assert p["type"] == "STOP_MARKET"
    assert p["reduceOnly"] == "true"
    assert "stopPrice" in p
    assert "timeInForce" not in p  # market-style stop carries no price/TIF


async def test_futures_market_close_sends_reduce_only_no_stop(gw) -> None:
    await gw.create_order(OrderRequest(
        symbol="BTCUSDT", side=Side.SELL, type=OrderType.MARKET,
        quantity=Decimal("0.5"), reduce_only=True,
    ))
    p = gw._captured["params"]
    assert p["type"] == "MARKET"
    assert p["reduceOnly"] == "true"
    assert "stopPrice" not in p
    assert "timeInForce" not in p


async def test_futures_entry_market_has_no_reduce_only(gw) -> None:
    await gw.create_order(OrderRequest(
        symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("0.5"),
    ))
    p = gw._captured["params"]
    assert p["type"] == "MARKET"
    assert "reduceOnly" not in p
