"""Integration test: the FastAPI backend via TestClient."""

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from quantbot.api.app import create_app  # noqa: E402
from quantbot.api.dependencies import AppState  # noqa: E402
from quantbot.core.constants import Side, Timeframe  # noqa: E402
from quantbot.portfolio.manager import PortfolioManager  # noqa: E402
from quantbot.risk.engine import RiskEngine  # noqa: E402

pytestmark = pytest.mark.integration


class _Strat:
    instance_name = "ema1"
    symbols = ["BTCUSDT"]
    timeframes = [Timeframe.H1]
    params = {"fast": 12}


@pytest.fixture
def client(settings):
    portfolio = PortfolioManager(starting_balance=Decimal("10000"))
    portfolio.positions.open_position(
        symbol="BTCUSDT", side=Side.BUY, quantity=Decimal("2"), entry_price=Decimal("100")
    )
    portfolio.update_price("BTCUSDT", Decimal("110"))
    portfolio.snapshot()
    risk = RiskEngine(settings.risk)
    risk.set_starting_equity(Decimal("10000"))
    state = AppState(
        settings=settings, portfolio=portfolio, risk_engine=risk, strategies=[_Strat()]
    )
    return TestClient(create_app(settings=settings, state=state))


def test_health_and_root(client: TestClient) -> None:
    assert client.get("/").json()["name"] == "QuantBot API"
    assert client.get("/health").json()["trading_mode"]


def test_portfolio_and_positions(client: TestClient) -> None:
    portfolio = client.get("/portfolio").json()
    assert portfolio["open_positions"] == 1
    assert Decimal(portfolio["equity"]) == Decimal("10020")
    positions = client.get("/positions").json()
    assert len(positions) == 1
    assert Decimal(positions[0]["unrealized_pnl"]) == Decimal("20")


def test_risk_emergency_flow(client: TestClient) -> None:
    assert client.get("/risk/status").json()["emergency_shutdown"] is False
    assert client.post("/system/emergency-stop").json()["ok"] is True
    assert client.get("/risk/status").json()["emergency_shutdown"] is True
    assert client.post("/system/resume").json()["ok"] is True
    assert client.get("/risk/status").json()["emergency_shutdown"] is False


def test_login(client: TestClient) -> None:
    ok = client.post("/auth/login", json={"username": "admin", "password": "x"})
    assert ok.status_code == 200 and "access_token" in ok.json()
    bad = client.post("/auth/login", json={"username": "nope", "password": "x"})
    assert bad.status_code == 401
