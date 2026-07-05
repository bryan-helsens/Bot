"""Bitvavo adapter: symbol mapping, signing, parsing, order mapping, factory
routing and the real-money interlock (Bitvavo has NO testnet)."""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

import pytest
from pydantic import SecretStr

from quantbot.core.config import Settings
from quantbot.core.constants import MarketType, OrderStatus, OrderType, Side, Timeframe, TradingMode
from quantbot.core.exceptions import ConfigurationError, SymbolNotFoundError
from quantbot.core.models import SymbolInfo
from quantbot.exchanges.base import OrderRequest
from quantbot.exchanges.bitvavo import BitvavoGateway
from quantbot.exchanges.factory import create_gateway

pytestmark = pytest.mark.unit


def _settings(**overrides) -> Settings:
    s = Settings(_env_file=None)
    s.exchange = "bitvavo"
    s.quote_asset = "EUR"
    s.symbols = ["BTCEUR", "ETHEUR"]
    s.bitvavo.api_key = "key"
    s.bitvavo.api_secret = SecretStr("secret")
    for key, val in overrides.items():
        setattr(s, key, val)
    return s


def _gateway() -> BitvavoGateway:
    gw = BitvavoGateway(_settings())
    gw._symbols["BTCEUR"] = SymbolInfo(
        symbol="BTCEUR", base_asset="BTC", quote_asset="EUR",
        step_size=Decimal("0.00000001"), min_notional=Decimal("5"),
    )
    return gw


# ------------------------------------------------------------------ symbols


def test_symbol_mapping_roundtrip() -> None:
    gw = _gateway()
    assert gw._to_market("BTCEUR") == "BTC-EUR"
    assert gw._from_market("BTC-EUR") == "BTCEUR"


def test_symbol_mapping_rejects_wrong_quote() -> None:
    gw = _gateway()
    with pytest.raises(SymbolNotFoundError):
        gw._to_market("BTCUSDT")  # quote asset is EUR


# ------------------------------------------------------------------ signing


def test_signature_matches_reference_hmac() -> None:
    gw = _gateway()
    sig = gw._sign(1700000000000, "GET", "/balance", "")
    expected = hmac.new(
        b"secret", b"1700000000000GET/v2/balance", hashlib.sha256
    ).hexdigest()
    assert sig == expected


# ------------------------------------------------------------------ parsing


async def test_klines_sorted_oldest_first(monkeypatch) -> None:
    gw = _gateway()
    # Bitvavo returns NEWEST first; the port contract is oldest first.
    rows = [
        [1700000600000, "101", "102", "100", "101.5", "10"],
        [1700000300000, "100", "101", "99", "100.5", "12"],
        [1700000000000, "99", "100", "98", "99.5", "9"],
    ]

    async def fake_request(method, path, **kwargs):
        assert path == "/BTC-EUR/candles"
        return rows

    monkeypatch.setattr(gw, "_request", fake_request)

    candles = await gw.get_klines("BTCEUR", Timeframe.M5)
    assert [float(c.close) for c in candles] == [99.5, 100.5, 101.5]
    assert candles[0].open_time < candles[-1].open_time
    assert candles[0].symbol == "BTCEUR"


def test_parse_order_maps_status_and_avg_price() -> None:
    gw = _gateway()
    data = {
        "orderId": "abc-123", "market": "BTC-EUR", "side": "buy",
        "status": "filled", "amount": "0.01",
        "filledAmount": "0.01", "filledAmountQuote": "652.5", "feePaid": "1.63",
    }
    order = gw._parse_order(data)
    assert order.exchange_order_id == "abc-123"
    assert order.symbol == "BTCEUR"
    assert order.status is OrderStatus.FILLED
    assert order.filled_qty == Decimal("0.01")
    assert order.avg_fill_price == Decimal("65250")
    assert order.commission == Decimal("1.63")


def test_partially_filled_and_canceled_statuses() -> None:
    gw = _gateway()
    assert gw._parse_order({"orderId": "1", "market": "BTC-EUR", "side": "sell",
                            "status": "partiallyFilled", "amount": "1"}).status is OrderStatus.PARTIALLY_FILLED
    assert gw._parse_order({"orderId": "2", "market": "BTC-EUR", "side": "sell",
                            "status": "canceledIOC", "amount": "1"}).status is OrderStatus.CANCELED


# ------------------------------------------------------------------ order bodies


def test_market_order_body_includes_operator_id() -> None:
    gw = _gateway()
    body = gw._build_order_body(
        OrderRequest(symbol="BTCEUR", side=Side.BUY, type=OrderType.MARKET,
                     quantity=Decimal("0.5")),
        Decimal("0.5"),
    )
    assert body == {
        "market": "BTC-EUR", "side": "buy", "orderType": "market",
        "amount": "0.5", "operatorId": 1001,
    }


def test_stop_loss_body_uses_trigger_fields() -> None:
    gw = _gateway()
    body = gw._build_order_body(
        OrderRequest(symbol="BTCEUR", side=Side.SELL, type=OrderType.STOP_LOSS,
                     quantity=Decimal("0.5"), stop_price=Decimal("60000")),
        Decimal("0.5"),
    )
    assert body["orderType"] == "stopLoss"
    assert body["triggerAmount"] == "60000"
    assert body["triggerType"] == "price"
    assert body["triggerReference"] == "lastTrade"
    assert "price" not in body and "timeInForce" not in body  # market-style stop


async def test_create_order_registers_client_id_for_cancel(monkeypatch) -> None:
    gw = _gateway()
    calls: list[tuple] = []

    async def fake_request(method, path, *, params=None, body=None, signed=False):
        calls.append((method, path, params, body))
        if path == "/order" and method == "POST":
            return {"orderId": "ex-42", "market": "BTC-EUR", "side": "buy",
                    "status": "filled", "amount": body["amount"],
                    "filledAmount": body["amount"], "filledAmountQuote": "500"}
        if path == "/order" and method == "DELETE":
            return {"orderId": params["orderId"]}
        raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr(gw, "_request", fake_request)

    order = await gw.create_order(OrderRequest(
        symbol="BTCEUR", side=Side.BUY, type=OrderType.MARKET,
        quantity=Decimal("0.01"), client_order_id="qb_stop_1",
    ))
    assert order.exchange_order_id == "ex-42"

    # Cancel by CLIENT id must resolve to the exchange id (Bitvavo has no client ids).
    cancelled = await gw.cancel_order("BTCEUR", client_order_id="qb_stop_1")
    assert cancelled.status is OrderStatus.CANCELED
    assert calls[-1][2]["orderId"] == "ex-42"


# ------------------------------------------------------------------ factory & interlock


def test_factory_routes_bitvavo() -> None:
    gw = create_gateway(_settings())
    assert isinstance(gw, BitvavoGateway)
    assert gw.market is MarketType.SPOT


def test_factory_rejects_unknown_exchange() -> None:
    with pytest.raises(ConfigurationError):
        create_gateway(_settings(exchange="kraken"))


def test_factory_default_binance_unchanged() -> None:
    from quantbot.exchanges.binance_spot import BinanceSpotGateway

    s = Settings(_env_file=None)
    assert isinstance(create_gateway(s), BinanceSpotGateway)


def test_live_bitvavo_requires_real_money_opt_in() -> None:
    from quantbot.engine.runtime import build_runtime

    s = _settings(trading_mode=TradingMode.LIVE)
    assert s.uses_fake_money is False  # no testnet on Bitvavo
    with pytest.raises(RuntimeError, match="REAL money"):
        build_runtime(s)


def test_paper_bitvavo_builds_without_opt_in() -> None:
    s = _settings(trading_mode=TradingMode.PAPER)
    s.strategies_config = "config/strategies.paper.example.yaml"
    from quantbot.engine.runtime import build_runtime

    runtime = build_runtime(s)  # must not raise: paper is simulated fills
    assert runtime.gateway is not None
