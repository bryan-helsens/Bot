"""Dashboard security (login gate), live strategy/risk tuning, and the honest
profitability report."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from quantbot.api.app import create_app
from quantbot.api.dependencies import AppState
from quantbot.core.config import Settings
from quantbot.core.constants import ExitReason, Side
from quantbot.portfolio.manager import PortfolioManager
from quantbot.strategies.builtin.rsi_strategy import RSIStrategy

pytestmark = pytest.mark.integration


# ----------------------------------------------------------------- security


def _secured_client():
    settings = Settings(_env_file=None)
    settings.api.dashboard_password = SecretStr("hunter2")
    settings.api.jwt_secret = SecretStr("a-real-secret")
    state = AppState(settings=settings, portfolio=PortfolioManager(starting_balance=Decimal("100")))
    return TestClient(create_app(settings=settings, state=state))


def test_auth_status_reports_required_when_password_set() -> None:
    client = _secured_client()
    assert client.get("/auth/status").json() == {"required": True}


def test_protected_endpoint_rejects_without_token() -> None:
    client = _secured_client()
    assert client.get("/portfolio").status_code == 401


def test_login_with_correct_password_grants_access() -> None:
    client = _secured_client()
    assert client.post("/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    resp = client.post("/auth/login", json={"username": "admin", "password": "hunter2"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    ok = client.get("/portfolio", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


def test_auth_off_by_default_in_dev() -> None:
    settings = Settings(_env_file=None)
    client = TestClient(create_app(settings=settings, state=AppState(settings=settings)))
    assert client.get("/auth/status").json() == {"required": False}
    assert client.get("/portfolio").status_code == 200


# ----------------------------------------------------------------- tuning


def test_strategy_params_update_live() -> None:
    settings = Settings(_env_file=None)
    strat = RSIStrategy(params={"oversold": 35.0})
    state = AppState(settings=settings, strategies=[strat])
    client = TestClient(create_app(settings=settings, state=state))

    name = client.get("/strategies").json()[0]["name"]
    resp = client.post(f"/strategies/{name}/params", json={"params": {"oversold": "42"}})
    assert resp.json()["ok"] is True
    assert strat.params["oversold"] == 42  # coerced to the param's numeric type


def test_strategy_params_reject_unknown_key() -> None:
    settings = Settings(_env_file=None)
    strat = RSIStrategy()
    client = TestClient(create_app(settings=settings, state=AppState(settings=settings, strategies=[strat])))
    name = client.get("/strategies").json()[0]["name"]
    resp = client.post(f"/strategies/{name}/params", json={"params": {"nonsense": "1"}})
    assert resp.json()["ok"] is False


def test_risk_params_update_live() -> None:
    settings = Settings(_env_file=None)
    client = TestClient(create_app(settings=settings, state=AppState(settings=settings)))
    resp = client.post("/system/risk-params", json={"risk_per_trade": "0.01"})
    assert resp.json()["ok"] is True
    assert settings.risk.risk_per_trade == Decimal("0.01")


def test_risk_params_reject_out_of_bounds() -> None:
    settings = Settings(_env_file=None)
    client = TestClient(create_app(settings=settings, state=AppState(settings=settings)))
    resp = client.post("/system/risk-params", json={"risk_per_trade": "5"})  # 500% -> rejected
    assert resp.json()["ok"] is False


# ----------------------------------------------------------------- report


def test_report_verdict_is_negative_when_losing() -> None:
    settings = Settings(_env_file=None)
    pf = PortfolioManager(starting_balance=Decimal("1000"))
    pf.positions.open_position(symbol="ETHUSDT", side=Side.BUY, quantity=Decimal("0.1"),
                               entry_price=Decimal("3200"), strategy="rsi", fee=Decimal("0"))
    pf.update_price("ETHUSDT", Decimal("3000"))
    pf.apply_trade(pf.positions.close_position("ETHUSDT", exit_price=Decimal("3000"),
                                               reason=ExitReason.STOP_LOSS))
    client = TestClient(create_app(settings=settings, state=AppState(settings=settings, portfolio=pf)))

    body = client.get("/portfolio/report?days=7").json()
    assert body["trades"] == 1
    assert float(body["net_pnl"]) < 0
    assert "real money" in body["verdict"].lower()
