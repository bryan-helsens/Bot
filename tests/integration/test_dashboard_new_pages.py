"""New dashboard surfaces: trade-analytics breakdown, account overview (capital
ledger) and the market-scanner / per-coin mute endpoints."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from quantbot.api.app import create_app
from quantbot.api.dependencies import AppState
from quantbot.core.config import Settings
from quantbot.core.constants import ExitReason, Side
from quantbot.portfolio.manager import PortfolioManager

pytestmark = pytest.mark.integration


def _portfolio_with_trades() -> PortfolioManager:
    pf = PortfolioManager(starting_balance=Decimal("10000"))
    # One winner on BTC, one loser on ETH, both via the same strategy.
    pf.positions.open_position(
        symbol="BTCUSDT", side=Side.BUY, quantity=Decimal("0.01"),
        entry_price=Decimal("65000"), strategy="rsi_dip_buyer", fee=Decimal("0"),
    )
    pf.update_price("BTCUSDT", Decimal("67000"))
    pf.apply_trade(
        pf.positions.close_position("BTCUSDT", exit_price=Decimal("67000"),
                                    reason=ExitReason.TAKE_PROFIT)
    )
    pf.positions.open_position(
        symbol="ETHUSDT", side=Side.BUY, quantity=Decimal("0.1"),
        entry_price=Decimal("3200"), strategy="rsi_dip_buyer", fee=Decimal("0"),
    )
    pf.update_price("ETHUSDT", Decimal("3100"))
    pf.apply_trade(
        pf.positions.close_position("ETHUSDT", exit_price=Decimal("3100"),
                                    reason=ExitReason.STOP_LOSS)
    )
    return pf


def _client(pf: PortfolioManager) -> TestClient:
    settings = Settings(_env_file=None)
    return TestClient(create_app(settings=settings, state=AppState(settings=settings, portfolio=pf)))


def test_analytics_breaks_down_by_coin_and_strategy() -> None:
    client = _client(_portfolio_with_trades())
    body = client.get("/portfolio/analytics").json()

    assert body["total_trades"] == 2
    assert body["quote_asset"] == "USDT"
    coins = {row["name"] for row in body["by_coin"]}
    assert coins == {"BTCUSDT", "ETHUSDT"}
    # One win, one loss → 50% win rate.
    assert body["win_rate"] == 0.5
    # Strategy rollup groups both under the one strategy.
    assert len(body["by_strategy"]) == 1
    assert body["by_strategy"][0]["name"] == "rsi_dip_buyer"
    assert body["by_strategy"][0]["trades"] == 2
    # Exit reasons counted.
    assert body["by_exit_reason"].get("take_profit") == 1
    assert body["by_exit_reason"].get("stop_loss") == 1


def test_account_balances_reports_bot_equity_without_engine() -> None:
    client = _client(_portfolio_with_trades())
    body = client.get("/account/balances").json()

    assert body["quote_asset"] == "USDT"
    assert float(body["bot_equity"]) > 0
    # No gateway wired (bare portfolio) → wallet equity is unknown, not fabricated.
    assert body["wallet_equity"] is None


def test_analytics_empty_when_no_trades() -> None:
    client = _client(PortfolioManager(starting_balance=Decimal("100")))
    body = client.get("/portfolio/analytics").json()
    assert body["total_trades"] == 0
    assert body["by_coin"] == []


def test_scanner_and_muted_safe_without_engine() -> None:
    client = _client(PortfolioManager(starting_balance=Decimal("100")))
    assert client.get("/market/scanner").json() == []
    assert client.get("/system/muted").json() == []
