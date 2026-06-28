"""Tax/fiscaal report: per-year realised figures + a CSV trade ledger an
accountant can use for a Belgian declaration."""

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


def _client_with_trades() -> TestClient:
    settings = Settings(_env_file=None)
    pf = PortfolioManager(starting_balance=Decimal("1000"))
    for sym, px, exitp in [("BTCUSDT", 100, 104), ("ETHUSDT", 50, 48)]:
        pf.positions.open_position(symbol=sym, side=Side.BUY, quantity=Decimal("1"),
                                   entry_price=Decimal(str(px)), strategy="rsi", fee=Decimal("0"))
        pf.update_price(sym, Decimal(str(exitp)))
        reason = ExitReason.TAKE_PROFIT if exitp > px else ExitReason.STOP_LOSS
        pf.apply_trade(pf.positions.close_position(sym, exit_price=Decimal(str(exitp)), reason=reason))
    return TestClient(create_app(settings=settings, state=AppState(settings=settings, portfolio=pf)))


def test_tax_report_groups_by_year() -> None:
    client = _client_with_trades()
    body = client.get("/tax/report").json()
    assert body["quote_asset"] == "USDT"
    assert body["is_testnet"] is True            # default settings = testnet
    assert len(body["years"]) == 1               # both trades closed this year
    year = body["years"][0]
    assert year["trades"] == 2
    assert year["wins"] == 1 and year["losses"] == 1
    # +4 on BTC, -2 on ETH -> net +2 realised.
    assert float(year["realized_pnl"]) == pytest.approx(2.0, abs=1e-6)
    assert "Vak XIII" in body["notes"]["foreign_account"]


def test_tax_csv_export_has_ledger_rows() -> None:
    client = _client_with_trades()
    resp = client.get("/tax/trades.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("opened_at,closed_at,symbol")
    assert len(lines) == 3                        # header + 2 trades
    assert "BTCUSDT" in resp.text and "ETHUSDT" in resp.text


def test_tax_report_empty_without_trades() -> None:
    settings = Settings(_env_file=None)
    client = TestClient(create_app(settings=settings, state=AppState(settings=settings)))
    body = client.get("/tax/report").json()
    assert body["years"] == []
