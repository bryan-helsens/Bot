"""Unit tests for position sizing."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import RiskSettings
from quantbot.core.constants import SizingMethod
from quantbot.risk.position_sizing import PositionSizer, SizingInput

pytestmark = pytest.mark.unit


@pytest.fixture
def sizer() -> PositionSizer:
    cfg = RiskSettings(
        risk_per_trade=Decimal("0.01"), max_exposure_per_coin=Decimal("0.20"),
        default_stop_loss_pct=Decimal("0.02"), kelly_cap=Decimal("0.25"),
    )
    return PositionSizer(cfg)


def test_risk_sizing(sizer: PositionSizer) -> None:
    r = sizer.size(
        SizingInput(equity=Decimal("10000"), price=Decimal("100"), stop_loss=Decimal("95")),
        method=SizingMethod.RISK,
    )
    assert r.quantity == Decimal("20")
    assert r.risk_amount == Decimal("100")


def test_exposure_cap(sizer: PositionSizer) -> None:
    r = sizer.size(
        SizingInput(equity=Decimal("10000"), price=Decimal("100"), stop_loss=Decimal("99")),
        method=SizingMethod.RISK,
    )
    assert r.notional == Decimal("2000")
    assert "exposure_capped" in r.reason


def test_kelly_negative_edge_is_zero(sizer: PositionSizer) -> None:
    r = sizer.size(
        SizingInput(
            equity=Decimal("10000"), price=Decimal("100"), stop_loss=Decimal("95"),
            win_rate=0.3, win_loss_ratio=1.0,
        ),
        method=SizingMethod.KELLY,
    )
    assert r.quantity == Decimal("0")


def test_volatility_sizing(sizer: PositionSizer) -> None:
    r = sizer.size(
        SizingInput(equity=Decimal("10000"), price=Decimal("100"), atr=Decimal("4")),
        method=SizingMethod.VOLATILITY,
    )
    assert r.method is SizingMethod.VOLATILITY
    assert r.notional == Decimal("2000")


def test_zero_equity_is_safe(sizer: PositionSizer) -> None:
    r = sizer.size(SizingInput(equity=Decimal("0"), price=Decimal("100")))
    assert r.quantity == Decimal("0")
