"""Min-notional handling: small orders are bumped to the exchange minimum, or
skipped cleanly when even the minimum is unaffordable (so €100 accounts trade)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import RiskSettings, Settings
from quantbot.core.constants import RiskDecision, Side, SizingMethod
from quantbot.core.models import SymbolInfo
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import OrderProposal, RiskEngine

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


class _MinNotionalGateway(MockGateway):
    def __init__(self, min_notional: Decimal) -> None:
        super().__init__()
        self._mn = min_notional

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(symbol=symbol, base_asset="BTC", quote_asset="USDT",
                          min_notional=self._mn, step_size=Decimal("0.00000001"))


def _executor(cash: Decimal, min_notional: Decimal) -> OrderExecutor:
    s = Settings(_env_file=None)
    s.risk = RiskSettings(sizing_method=SizingMethod.RISK)
    portfolio = PortfolioManager(starting_balance=cash)
    risk = RiskEngine(s.risk)
    return OrderExecutor(_MinNotionalGateway(min_notional), risk, portfolio, commission_rate=Decimal("0"))


def _proposal(qty: str, price: str) -> OrderProposal:
    return OrderProposal(decision=RiskDecision.APPROVED, symbol="BTCUSDT", side=Side.BUY,
                         quantity=Decimal(qty), price=Decimal(price))


async def test_small_order_is_bumped_to_min_notional() -> None:
    ex = _executor(cash=Decimal("10000"), min_notional=Decimal("200"))
    # notional 1 * 100 = 100 < 200 -> bump to >= 200.
    out = await ex._enforce_min_notional(_proposal("1", "100"))
    assert out is not None
    assert out.quantity * out.price >= Decimal("200")


async def test_order_already_above_min_is_unchanged() -> None:
    ex = _executor(cash=Decimal("10000"), min_notional=Decimal("50"))
    out = await ex._enforce_min_notional(_proposal("1", "100"))  # notional 100 >= 50
    assert out is not None
    assert out.quantity == Decimal("1")


async def test_order_skipped_when_min_unaffordable() -> None:
    ex = _executor(cash=Decimal("50"), min_notional=Decimal("200"))
    out = await ex._enforce_min_notional(_proposal("0.1", "100"))  # bump to ~202 > 50 cash
    assert out is None


async def test_no_min_notional_passes_through() -> None:
    ex = _executor(cash=Decimal("10000"), min_notional=Decimal("0"))
    out = await ex._enforce_min_notional(_proposal("0.01", "100"))
    assert out is not None
    assert out.quantity == Decimal("0.01")
