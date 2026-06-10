"""The dashboard API must serve the LIVE engine state when wired in one process.

`quantbot serve` shares the running engine's PortfolioManager with the API via
AppState; this guards that the REST layer reflects that shared state (and that a
bare API with no engine returns safe empty data, as `quantbot api` alone would).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from quantbot.api.app import create_app
from quantbot.api.dependencies import AppState
from quantbot.core.config import Settings
from quantbot.portfolio.manager import PortfolioManager

pytestmark = pytest.mark.integration


def test_dashboard_serves_live_portfolio_state() -> None:
    settings = Settings(_env_file=None)  # dev + default jwt secret -> auth bypassed
    portfolio = PortfolioManager(starting_balance=Decimal("12345"))
    state = AppState(settings=settings, portfolio=portfolio)
    client = TestClient(create_app(settings=settings, state=state))

    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["equity"] == "12345"
    assert body["cash"] == "12345"


def test_dashboard_returns_empty_without_engine_state() -> None:
    settings = Settings(_env_file=None)
    client = TestClient(create_app(settings=settings))  # bare state, no portfolio

    resp = client.get("/portfolio")
    assert resp.status_code == 200
    assert resp.json()["open_positions"] == 0


def test_dashboard_populates_trades_equity_and_performance() -> None:
    """With portfolio + performance wired (as `quantbot demo` does), every panel
    has data: closed trades, an equity curve and per-strategy performance."""
    from quantbot.core.constants import ExitReason, Side
    from quantbot.portfolio.performance import PerformanceTracker

    settings = Settings(_env_file=None)
    pf = PortfolioManager(starting_balance=Decimal("10000"))
    perf = PerformanceTracker(starting_equity=10000.0)
    for sym, px in [("BTCUSDT", 65000.0), ("ETHUSDT", 3200.0)]:
        pf.positions.open_position(
            symbol=sym, side=Side.BUY, quantity=Decimal("0.01"),
            entry_price=Decimal(str(px)), strategy="rsi_dip_buyer", fee=Decimal("0"),
        )
        exitp = Decimal(str(px * 1.04))
        pf.update_price(sym, exitp)
        trade = pf.positions.close_position(sym, exit_price=exitp, reason=ExitReason.TAKE_PROFIT)
        pf.apply_trade(trade)
        perf.add_trade(trade)
        pf.snapshot()

    state = AppState(settings=settings, portfolio=pf, performance=perf)
    client = TestClient(create_app(settings=settings, state=state))

    assert len(client.get("/trades").json()) == 2
    assert len(client.get("/portfolio/equity-curve").json()) == 2
    assert len(client.get("/strategies/performance").json()) == 1


def test_daily_pnl_aggregates_closed_trades() -> None:
    from quantbot.core.constants import ExitReason, Side
    from quantbot.portfolio.performance import PerformanceTracker

    settings = Settings(_env_file=None)
    pf = PortfolioManager(starting_balance=Decimal("10000"))
    perf = PerformanceTracker(starting_equity=10000.0)
    for sym, px in [("BTCUSDT", 65000.0), ("ETHUSDT", 3200.0)]:
        pf.positions.open_position(symbol=sym, side=Side.BUY, quantity=Decimal("0.01"),
                                   entry_price=Decimal(str(px)), strategy="rsi", fee=Decimal("0"))
        exitp = Decimal(str(px * 1.04))
        pf.update_price(sym, exitp)
        trade = pf.positions.close_position(sym, exit_price=exitp, reason=ExitReason.TAKE_PROFIT)
        pf.apply_trade(trade)
        perf.add_trade(trade)

    client = TestClient(create_app(settings=settings, state=AppState(settings=settings, portfolio=pf, performance=perf)))
    pnl = client.get("/portfolio/daily-pnl").json()
    assert len(pnl) == 1  # both closed today
    assert pnl[0]["trades"] == 2
    assert pnl[0]["pnl"] > 0
