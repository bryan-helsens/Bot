"""Portfolio aggregation: equity, balances, allocation and exposure.

:class:`PortfolioManager` is the single source of truth for account-level state.
It tracks cash balance and realised PnL, derives equity (cash + unrealised PnL),
records periodic equity snapshots for the equity curve, and exposes exposure /
allocation views used by the risk engine and dashboard.

It composes a :class:`~quantbot.portfolio.position.PositionManager` for the
position-level detail and provides the
:class:`~quantbot.risk.engine.PortfolioView` the risk engine consumes.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from quantbot.core.logging import LoggerMixin
from quantbot.core.models import AccountSnapshot, Position, Trade, utcnow
from quantbot.portfolio.position import PositionManager
from quantbot.risk.engine import PortfolioView


class PortfolioManager(LoggerMixin):
    """Track equity, balances, exposure and allocation across all assets."""

    def __init__(
        self,
        *,
        starting_balance: Decimal,
        quote_asset: str = "USDT",
        snapshot_history: int = 10_000,
    ) -> None:
        self._quote = quote_asset
        self._starting_balance = starting_balance
        self._cash = starting_balance
        self._realized_pnl = Decimal("0")
        self._fees_paid = Decimal("0")
        self.positions = PositionManager()
        self._snapshots: deque[AccountSnapshot] = deque(maxlen=snapshot_history)
        self._peak_equity = starting_balance
        self._prices: dict[str, Decimal] = {}

    # ------------------------------------------------------------------ prices

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Record the latest price and update the position mark price."""
        self._prices[symbol] = price
        self.positions.update_mark_price(symbol, price)

    def update_prices(self, prices: dict[str, Decimal]) -> None:
        for symbol, price in prices.items():
            self.update_price(symbol, price)

    def price_of(self, symbol: str) -> Decimal | None:
        return self._prices.get(symbol)

    # ------------------------------------------------------------------ cash / pnl

    def reserve_cash(self, amount: Decimal) -> None:
        """Deduct notional cash when opening/scaling a position (spot)."""
        self._cash -= amount

    def release_cash(self, amount: Decimal) -> None:
        """Return notional cash when closing a position (spot)."""
        self._cash += amount

    def apply_trade(self, trade: Trade) -> None:
        """Apply a realised trade's PnL and fees to the portfolio."""
        self._realized_pnl += trade.net_pnl
        self._fees_paid += trade.fees
        self._cash += trade.net_pnl
        self.log.debug(
            "trade_applied", symbol=trade.symbol, net_pnl=float(trade.net_pnl),
            realized_total=float(self._realized_pnl),
        )

    def apply_fee(self, fee: Decimal) -> None:
        """Apply a standalone fee (e.g. on entry) to cash."""
        self._cash -= fee
        self._fees_paid += fee

    # ------------------------------------------------------------------ equity

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def realized_pnl(self) -> Decimal:
        return self._realized_pnl

    @property
    def fees_paid(self) -> Decimal:
        return self._fees_paid

    def unrealized_pnl(self) -> Decimal:
        return self.positions.total_unrealized_pnl(self._prices)

    def equity(self) -> Decimal:
        """Total account equity = cash + unrealised PnL of open positions."""
        return self._cash + self.unrealized_pnl()

    def exposure(self) -> Decimal:
        """Total notional exposure across open positions."""
        return self.positions.total_exposure(self._prices)

    def exposure_pct(self) -> Decimal:
        equity = self.equity()
        return self.exposure() / equity if equity > 0 else Decimal("0")

    def total_return_pct(self) -> Decimal:
        if self._starting_balance <= 0:
            return Decimal("0")
        return (self.equity() - self._starting_balance) / self._starting_balance

    # ------------------------------------------------------------------ allocation

    def allocation(self) -> dict[str, Decimal]:
        """Fraction of equity allocated to each open position symbol."""
        equity = self.equity()
        if equity <= 0:
            return {}
        out: dict[str, Decimal] = {}
        for position in self.positions.all_open():
            price = self._prices.get(position.symbol, position.mark_price)
            out[position.symbol] = position.notional(price) / equity
        return out

    # ------------------------------------------------------------------ snapshots

    def snapshot(self) -> AccountSnapshot:
        """Capture and store a point-in-time equity snapshot."""
        equity = self.equity()
        self._peak_equity = max(self._peak_equity, equity)
        drawdown = (
            (self._peak_equity - equity) / self._peak_equity if self._peak_equity > 0 else Decimal("0")
        )
        snap = AccountSnapshot(
            timestamp=utcnow(),
            equity=equity,
            balance=self._cash,
            unrealized_pnl=self.unrealized_pnl(),
            used_margin=self.exposure(),
            open_positions=self.positions.open_count,
            drawdown=max(Decimal("0"), drawdown),
        )
        self._snapshots.append(snap)
        return snap

    def snapshots(self) -> list[AccountSnapshot]:
        return list(self._snapshots)

    def equity_curve(self) -> list[tuple[str, float]]:
        """Equity curve as ``(iso_timestamp, equity)`` points for the dashboard."""
        return [(s.timestamp.isoformat(), float(s.equity)) for s in self._snapshots]

    @property
    def max_drawdown(self) -> Decimal:
        """Maximum drawdown observed across stored snapshots."""
        return max((s.drawdown for s in self._snapshots), default=Decimal("0"))

    # ------------------------------------------------------------------ risk view

    def risk_view(self) -> PortfolioView:
        """Build the :class:`PortfolioView` consumed by the risk engine."""
        return PortfolioView(
            equity=self.equity(),
            available_balance=self._cash,
            open_positions=self.positions.all_open(),
        )

    def open_positions(self) -> list[Position]:
        return self.positions.all_open()


__all__ = ["PortfolioManager"]
