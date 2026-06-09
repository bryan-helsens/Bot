"""Engine state must survive a restart: cash, positions and equity curve round-trip."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.constants import ExitReason, Side
from quantbot.engine.state_store import load_state, save_state
from quantbot.portfolio.manager import PortfolioManager

pytestmark = pytest.mark.integration


def _seed() -> PortfolioManager:
    pf = PortfolioManager(starting_balance=Decimal("10000"))
    # One closed trade (realised PnL) + one still-open position + a snapshot.
    pf.positions.open_position(symbol="ETHUSDT", side=Side.BUY, quantity=Decimal("1"),
                               entry_price=Decimal("3000"), strategy="rsi", fee=Decimal("0"))
    pf.update_price("ETHUSDT", Decimal("3100"))
    trade = pf.positions.close_position("ETHUSDT", exit_price=Decimal("3100"),
                                        reason=ExitReason.TAKE_PROFIT)
    pf.apply_trade(trade)
    pf.positions.open_position(symbol="BTCUSDT", side=Side.BUY, quantity=Decimal("0.05"),
                               entry_price=Decimal("65000"), strategy="rsi",
                               stop_loss=Decimal("63000"), fee=Decimal("0"))
    pf.update_price("BTCUSDT", Decimal("66000"))
    pf.snapshot()
    return pf


def test_export_import_round_trip() -> None:
    pf = _seed()
    restored = PortfolioManager(starting_balance=Decimal("1"))  # different start
    restored.import_state(pf.export_state())

    assert restored.cash == pf.cash
    assert restored.realized_pnl == pf.realized_pnl
    assert restored.positions.has_position("BTCUSDT")
    assert not restored.positions.has_position("ETHUSDT")  # was closed
    pos = restored.positions.get("BTCUSDT")
    assert pos.quantity == Decimal("0.05")
    assert pos.stop_loss == Decimal("63000")
    assert len(restored.equity_curve()) == len(pf.equity_curve())


def test_save_and_load_file(tmp_path) -> None:
    pf = _seed()
    path = str(tmp_path / "state.json")
    assert save_state(pf, path) is True

    restored = PortfolioManager(starting_balance=Decimal("1"))
    assert load_state(restored, path) is True
    assert restored.cash == pf.cash
    assert restored.positions.open_count == pf.positions.open_count


def test_load_missing_file_is_noop() -> None:
    restored = PortfolioManager(starting_balance=Decimal("10000"))
    assert load_state(restored, "/nonexistent/path/state.json") is False
    assert restored.cash == Decimal("10000")


def test_empty_path_disables_persistence() -> None:
    pf = _seed()
    assert save_state(pf, "") is False
    assert load_state(pf, "") is False
