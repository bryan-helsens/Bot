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
