"""Unit tests for the risk engine and its limit components."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import RiskSettings
from quantbot.core.constants import (
    PositionSide,
    RiskDecision,
    RiskEventType,
    Side,
    Timeframe,
)
from quantbot.core.models import Position, Signal
from quantbot.risk.circuit_breaker import CircuitBreaker, EmergencyShutdown
from quantbot.risk.engine import PortfolioView, RiskEngine
from quantbot.risk.limits import LimitChecker

pytestmark = pytest.mark.unit


def _signal() -> Signal:
    return Signal(
        strategy="s", symbol="BTCUSDT", timeframe=Timeframe.H1, side=Side.BUY,
        price=Decimal("100"), stop_loss=Decimal("98"), strength=0.8,
    )


@pytest.fixture
def engine(risk_settings: RiskSettings) -> RiskEngine:
    eng = RiskEngine(risk_settings)
    eng.set_starting_equity(Decimal("10000"))
    return eng


async def test_approves_normal_trade(engine: RiskEngine) -> None:
    pf = PortfolioView(equity=Decimal("10000"), available_balance=Decimal("10000"))
    proposal = await engine.evaluate(_signal(), pf)
    assert proposal.approved and proposal.quantity > 0
    assert proposal.stop_loss == Decimal("98")


async def test_emergency_shutdown_rejects(engine: RiskEngine) -> None:
    engine.emergency.trigger("halt")
    pf = PortfolioView(equity=Decimal("10000"), available_balance=Decimal("10000"))
    proposal = await engine.evaluate(_signal(), pf)
    assert proposal.rejected and proposal.event_type is RiskEventType.EMERGENCY_SHUTDOWN


async def test_max_open_trades_rejects(engine: RiskEngine) -> None:
    positions = [
        Position(symbol=f"C{i}", side=PositionSide.LONG, quantity=Decimal("1"), entry_price=Decimal("100"))
        for i in range(5)
    ]
    pf = PortfolioView(equity=Decimal("10000"), available_balance=Decimal("10000"), open_positions=positions)
    proposal = await engine.evaluate(_signal(), pf)
    assert proposal.rejected and proposal.event_type is RiskEventType.MAX_OPEN_TRADES


async def test_drawdown_triggers_emergency(risk_settings: RiskSettings) -> None:
    risk_settings.max_drawdown = Decimal("0.20")
    eng = RiskEngine(risk_settings)
    eng.set_starting_equity(Decimal("10000"))
    eng.update_equity(Decimal("10000"))
    eng.update_equity(Decimal("7900"))  # 21% drawdown
    assert eng.emergency.active


def test_circuit_breaker_trips_and_resets() -> None:
    clock = {"t": 0.0}
    cfg = RiskSettings(circuit_breaker_losses=3, circuit_breaker_cooldown=60)
    cb = CircuitBreaker(cfg, time_fn=lambda: clock["t"])
    assert not cb.record_trade(Decimal("-1"))
    assert not cb.record_trade(Decimal("-1"))
    assert cb.record_trade(Decimal("-1"))
    assert cb.is_tripped
    clock["t"] += 61
    assert not cb.is_tripped


def test_martingale_blocked(risk_settings: RiskSettings) -> None:
    risk_settings.allow_martingale = False
    lc = LimitChecker(risk_settings)
    pos = Position(symbol="X", side=PositionSide.LONG, quantity=Decimal("1"),
                   entry_price=Decimal("100"), averaging_entries=1)
    check = lc.check_averaging(pos, Decimal("2"), Decimal("1"))
    assert not check.passed and check.event_type is RiskEventType.MARTINGALE_BLOCKED


def test_emergency_shutdown_latches() -> None:
    es = EmergencyShutdown()
    es.trigger("first")
    es.trigger("second")
    assert es.reason == "first"  # keeps first reason
    es.reset()
    assert not es.active
