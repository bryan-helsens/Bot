"""Simulated broker for backtesting.

Models realistic execution costs so backtest results are not optimistic:

* **Commission** — a fraction of notional charged per fill (both sides).
* **Slippage** — adverse price movement proportional to notional/side.
* **Spread** — half-spread paid when crossing the book (buy at ask, sell at bid).

The broker is intentionally minimal: given a side, quantity and the reference
price for the current bar, it returns the executed fill price and commission.
The :class:`~quantbot.backtest.engine.BacktestEngine` drives it bar by bar and
owns position/stop logic via the same domain components used live, guaranteeing
backtest behaviour matches production.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantbot.core.constants import Side


@dataclass(slots=True)
class Fill:
    """The result of a simulated fill."""

    price: Decimal
    quantity: Decimal
    commission: Decimal

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity


class SimulatedBroker:
    """Compute fill prices and commissions with cost modelling."""

    def __init__(
        self,
        *,
        commission: Decimal = Decimal("0.001"),
        slippage: Decimal = Decimal("0.0005"),
        spread: Decimal = Decimal("0.0002"),
    ) -> None:
        self._commission = commission
        self._slippage = slippage
        self._half_spread = spread / 2

    def fill(self, side: Side, quantity: Decimal, reference_price: Decimal) -> Fill:
        """Fill *quantity* at *reference_price* adjusted for spread + slippage.

        Buyers pay the half-spread plus slippage *above* the reference; sellers
        receive the half-spread plus slippage *below* it.
        """
        adjustment = self._half_spread + self._slippage
        if side is Side.BUY:
            price = reference_price * (Decimal(1) + adjustment)
        else:
            price = reference_price * (Decimal(1) - adjustment)
        commission = price * quantity * self._commission
        return Fill(price=price, quantity=quantity, commission=commission)

    def fill_at(self, side: Side, quantity: Decimal, exact_price: Decimal) -> Fill:
        """Fill at an *exact* price (e.g. a stop/limit trigger) with commission only.

        Slippage past a stop is modelled as the configured slippage in the
        adverse direction so stop exits are not unrealistically precise.
        """
        if side is Side.BUY:
            price = exact_price * (Decimal(1) + self._slippage)
        else:
            price = exact_price * (Decimal(1) - self._slippage)
        commission = price * quantity * self._commission
        return Fill(price=price, quantity=quantity, commission=commission)

    @property
    def commission_rate(self) -> Decimal:
        return self._commission


__all__ = ["Fill", "SimulatedBroker"]
