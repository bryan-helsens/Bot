"""Integration test: Binance gateway signing & payload mapping (no network)."""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

import pytest

from quantbot.core.config import Settings
from quantbot.core.constants import OrderStatus, Side, Timeframe
from quantbot.core.exceptions import (
    AuthenticationError,
    InsufficientBalanceError,
    OrderNotFoundError,
    RateLimitError,
    SymbolNotFoundError,
)
from quantbot.exchanges.binance_futures import BinanceFuturesGateway
from quantbot.exchanges.binance_spot import BinanceSpotGateway

pytestmark = pytest.mark.integration

_SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0"


@pytest.fixture
def spot() -> BinanceSpotGateway:
    s = Settings(_env_file=None)
    s.binance.api_key = "key"
    s.binance.api_secret = type(s.binance.api_secret)(_SECRET)
    return BinanceSpotGateway(s)


def test_hmac_signing(spot: BinanceSpotGateway) -> None:
    query = "symbol=LTCBTC&side=BUY&type=LIMIT&quantity=1&price=0.1&timestamp=1499827319559"
    expected = hmac.new(_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    assert spot._sign(query) == expected


def test_parse_kline(spot: BinanceSpotGateway) -> None:
    row = [1499040000000, "0.01", "0.02", "0.005", "0.015", "100",
           1499040059999, "1.5", 50, "10", "0.1", "0"]
    candle = spot._parse_kline("BTCUSDT", Timeframe.M1, row)
    assert candle.open == Decimal("0.01")
    assert candle.close == Decimal("0.015")
    assert candle.trades == 50


def test_parse_order(spot: BinanceSpotGateway) -> None:
    data = {
        "symbol": "BTCUSDT", "orderId": 123, "clientOrderId": "abc", "side": "BUY",
        "type": "LIMIT", "status": "FILLED", "timeInForce": "GTC", "origQty": "2",
        "price": "100", "executedQty": "2", "cummulativeQuoteQty": "200",
    }
    order = spot._parse_order(data)
    assert order.exchange_order_id == "123"
    assert order.status is OrderStatus.FILLED
    assert order.avg_fill_price == Decimal("100")
    assert order.side is Side.BUY


@pytest.mark.parametrize(
    ("status", "code", "exc"),
    [
        (429, -1003, RateLimitError),
        (401, -2014, AuthenticationError),
        (400, -2010, InsufficientBalanceError),
        (400, -2011, OrderNotFoundError),
        (400, -1121, SymbolNotFoundError),
    ],
)
def test_error_mapping(spot: BinanceSpotGateway, status: int, code: int, exc: type) -> None:
    with pytest.raises(exc):
        spot._raise_for_error(status, {"code": code, "msg": "x"})


def test_futures_position_parsing() -> None:
    s = Settings(_env_file=None)
    gw = BinanceFuturesGateway(s)
    data = {"symbol": "BTCUSDT", "positionAmt": "-2", "entryPrice": "2000",
            "markPrice": "1900", "leverage": "5", "unRealizedProfit": "200"}
    pos = gw._parse_position(data)
    assert pos.side.value == "short"
    assert pos.quantity == Decimal("2")
    assert pos.leverage == 5
