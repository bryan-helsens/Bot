"""A reduce-only spot SELL must be clamped to the free base balance (no over-sell)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import Settings
from quantbot.core.constants import MarketType, OrderType, Side
from quantbot.core.models import Balance, Order, OrderStatus, SymbolInfo
from quantbot.exchanges.base import OrderRequest
from quantbot.exchanges.binance_spot import BinanceSpotGateway

pytestmark = pytest.mark.unit


@pytest.fixture
def gw(monkeypatch):
    gateway = BinanceSpotGateway(Settings(_env_file=None))
    captured: dict = {}

    async def fake_symbol_info(symbol):
        return SymbolInfo(symbol=symbol, base_asset="BTC", quote_asset="USDT",
                          tick_size=Decimal("0.1"), step_size=Decimal("0.001"))

    async def fake_balance(asset):
        return Balance(asset=asset, free=captured.get("free", Decimal("0.6")))

    async def fake_request(method, path, *, params=None, **kw):
        captured["params"] = params
        return {}

    def fake_parse(data, request=None):
        p = captured["params"]
        return Order(client_order_id="x", symbol=p["symbol"], side=Side(p["side"].lower()),
                     type=OrderType.MARKET, quantity=Decimal(p["quantity"]), status=OrderStatus.NEW)

    monkeypatch.setattr(gateway, "get_symbol_info", fake_symbol_info)
    monkeypatch.setattr(gateway, "get_balance", fake_balance)
    monkeypatch.setattr(gateway, "_request", fake_request)
    monkeypatch.setattr(gateway, "_parse_order", fake_parse)
    gateway._captured = captured  # type: ignore[attr-defined]
    return gateway


async def test_reduce_sell_clamped_to_free_balance(gw) -> None:
    gw._captured["free"] = Decimal("0.6")
    await gw.create_order(OrderRequest(
        symbol="BTCUSDT", side=Side.SELL, type=OrderType.MARKET,
        quantity=Decimal("1.0"), reduce_only=True,
    ))
    assert Decimal(gw._captured["params"]["quantity"]) == Decimal("0.600")


async def test_entry_buy_not_clamped(gw) -> None:
    gw._captured["free"] = Decimal("0.6")
    await gw.create_order(OrderRequest(
        symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, quantity=Decimal("1.0"),
    ))
    # A non-reduce buy is never clamped by base balance.
    assert Decimal(gw._captured["params"]["quantity"]) == Decimal("1.000")


async def test_spot_stop_loss_omits_time_in_force(gw) -> None:
    """A spot STOP_LOSS (market stop) must send only stopPrice — no timeInForce/price."""
    await gw.create_order(OrderRequest(
        symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_LOSS,
        quantity=Decimal("0.5"), stop_price=Decimal("90"), reduce_only=True,
    ))
    p = gw._captured["params"]
    assert p["type"] == "STOP_LOSS"
    assert "stopPrice" in p
    assert "timeInForce" not in p, "STOP_LOSS must not carry timeInForce (-1106)"
    assert "price" not in p


async def test_spot_limit_keeps_time_in_force(gw) -> None:
    await gw.create_order(OrderRequest(
        symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT,
        quantity=Decimal("0.5"), price=Decimal("100"),
    ))
    p = gw._captured["params"]
    assert p["type"] == "LIMIT"
    assert "timeInForce" in p
    assert "price" in p
