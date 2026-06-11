"""On live spot, a booked position must be corrected to the real account balance —
so a thin meme pair that under-fills can't inflate the books (phantom holdings)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantbot.core.config import RiskSettings, Settings
from quantbot.core.constants import Side, SizingMethod
from quantbot.core.models import Balance, SymbolInfo
from quantbot.execution.executor import OrderExecutor
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import RiskEngine

from tests.conftest import MockGateway

pytestmark = pytest.mark.integration


class _BalanceGateway(MockGateway):  # market=SPOT, not a paper broker
    def __init__(self, held: Decimal) -> None:
        super().__init__()
        self._held = held

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(symbol=symbol, base_asset="PEPE", quote_asset="USDT")

    async def get_balance(self, asset: str) -> Balance:
        return Balance(asset=asset, free=self._held)


def _setup(held: Decimal):
    s = Settings(_env_file=None)
    s.risk = RiskSettings(sizing_method=SizingMethod.RISK)
    pf = PortfolioManager(starting_balance=Decimal("10000"))
    ex = OrderExecutor(_BalanceGateway(held), RiskEngine(s.risk), pf, commission_rate=Decimal("0"))
    pf.positions.open_position(symbol="PEPEUSDT", side=Side.BUY,
                               quantity=Decimal("949000000"), entry_price=Decimal("0.00000281"),
                               fee=Decimal("0"))
    return ex, pf


async def test_spot_fill_corrects_overbooked_position() -> None:
    ex, pf = _setup(held=Decimal("18446"))  # account only really holds 18,446
    await ex._verify_spot_fill(pf.positions.get("PEPEUSDT"))
    assert pf.positions.get("PEPEUSDT").quantity == Decimal("18446")


async def test_spot_fill_drops_position_when_nothing_filled() -> None:
    ex, pf = _setup(held=Decimal("0"))  # nothing actually filled
    await ex._verify_spot_fill(pf.positions.get("PEPEUSDT"))
    assert not pf.positions.has_position("PEPEUSDT")


async def test_spot_fill_keeps_position_when_balance_matches() -> None:
    ex, pf = _setup(held=Decimal("949000000"))  # books match reality
    await ex._verify_spot_fill(pf.positions.get("PEPEUSDT"))
    assert pf.positions.get("PEPEUSDT").quantity == Decimal("949000000")
