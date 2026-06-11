"""A position too small to sell (below min notional) must close in the books
instead of erroring every candle — and must never crash the candle cycle."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import RiskSettings, Settings
from quantbot.core.constants import Side, SizingMethod
from quantbot.core.exceptions import ExchangeError
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


class _DustGateway(MockGateway):
    async def create_order(self, request):
        if request.side is Side.SELL:
            raise ExchangeError("Filter failure: NOTIONAL", code=-1013)
        return await super().create_order(request)


def _executor():
    from quantbot.execution.executor import OrderExecutor

    s = Settings(_env_file=None)
    s.risk = RiskSettings(sizing_method=SizingMethod.RISK)
    portfolio = PortfolioManager(starting_balance=Decimal("10000"))
    risk = RiskEngine(s.risk)
    ex = OrderExecutor(_DustGateway(), risk, portfolio, commission_rate=Decimal("0"))
    return ex, portfolio


async def test_dust_close_closes_locally_without_raising() -> None:
    ex, portfolio = _executor()
    portfolio.positions.open_position(symbol="PEPEUSDT", side=Side.BUY,
                                      quantity=Decimal("18446"), entry_price=Decimal("0.000012"),
                                      fee=Decimal("0"))
    portfolio.update_price("PEPEUSDT", Decimal("0.000012"))
    pos = portfolio.positions.get("PEPEUSDT")

    result = await ex.close_position(pos, exit_price=Decimal("0.000012"))

    assert result is None, "no exchange order is placed for unsellable dust"
    assert not portfolio.positions.has_position("PEPEUSDT"), "closed in the books"
