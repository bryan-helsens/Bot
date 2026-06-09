"""Spot account equity must value base-asset holdings; get_balance stays cheap."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import Settings
from quantbot.core.models import Balance, Ticker
from quantbot.exchanges.binance_spot import BinanceSpotGateway

pytestmark = pytest.mark.unit


@pytest.fixture
def gw(monkeypatch):
    gateway = BinanceSpotGateway(Settings(_env_file=None))
    calls = {"ticker": 0}

    async def fake_balances():
        return {
            "USDT": Balance(asset="USDT", free=Decimal("1000")),
            "BTC": Balance(asset="BTC", free=Decimal("0.5")),
        }

    async def fake_ticker(symbol):
        calls["ticker"] += 1
        return Ticker(symbol=symbol, last_price=Decimal("100"))

    monkeypatch.setattr(gateway, "_fetch_balances", fake_balances)
    monkeypatch.setattr(gateway, "get_ticker", fake_ticker)
    gateway._calls = calls  # type: ignore[attr-defined]
    return gateway


async def test_equity_includes_base_holdings_at_price(gw) -> None:
    acct = await gw.get_account()
    # 1000 USDT + 0.5 BTC * 100 = 1050.
    assert acct.total_equity == Decimal("1050")
    assert acct.available_balance == Decimal("1000")


async def test_get_balance_is_cheap_no_ticker_calls(gw) -> None:
    bal = await gw.get_balance("BTC")
    assert bal.free == Decimal("0.5")
    assert gw._calls["ticker"] == 0, "get_balance must not value via tickers"
