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

    def apply_trade(self, trade: Trade) -> None:
        """Apply a realised trade's PnL and fees to cash.

        Equity is tracked on a PnL basis: cash only moves when PnL is realised.
        Opening a position does not move cash — the position's unrealised PnL
        (less the entry fees it has already accrued) is reflected in
        :meth:`equity`. ``trade.net_pnl`` already nets all fees, so no separate
        fee deduction is applied here. This is side-agnostic and therefore
        correct for both long and short positions.
        """
        self._realized_pnl += trade.net_pnl
        self._fees_paid += trade.fees
        self._cash += trade.net_pnl
        self.log.debug(
            "trade_applied", symbol=trade.symbol, net_pnl=float(trade.net_pnl),
            realized_total=float(self._realized_pnl),
        )

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

    def _open_fees(self) -> Decimal:
        """Fees already accrued on currently-open positions (not yet realised)."""
        return sum((p.fees_paid for p in self.positions.all_open()), Decimal("0"))

    def equity(self) -> Decimal:
        """Total account equity (side-agnostic, PnL based).

        ``equity = cash + unrealised_pnl − fees_on_open_positions``. Correct for
        both long and short: a short that moves against us yields negative
        unrealised PnL and lowers equity, as it must.
        """
        return self._cash + self.unrealized_pnl() - self._open_fees()

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

    # ------------------------------------------------------------------ persistence

    def export_state(self) -> dict:
        """Serialise the full account state (for restart persistence)."""
        return {
            "starting_balance": str(self._starting_balance),
            "cash": str(self._cash),
            "realized_pnl": str(self._realized_pnl),
            "fees_paid": str(self._fees_paid),
            "peak_equity": str(self._peak_equity),
            "prices": {sym: str(price) for sym, price in self._prices.items()},
            "positions": [p.model_dump(mode="json") for p in self.positions.all_open()],
            "snapshots": [s.model_dump(mode="json") for s in list(self._snapshots)[-2000:]],
        }

    def import_state(self, state: dict) -> None:
        """Restore account state produced by :meth:`export_state`."""
        from quantbot.core.models import AccountSnapshot, Position

        self._starting_balance = Decimal(str(state.get("starting_balance", self._starting_balance)))
        self._cash = Decimal(str(state["cash"]))
        self._realized_pnl = Decimal(str(state.get("realized_pnl", "0")))
        self._fees_paid = Decimal(str(state.get("fees_paid", "0")))
        self._peak_equity = Decimal(str(state.get("peak_equity", state["cash"])))
        self._prices = {sym: Decimal(str(p)) for sym, p in state.get("prices", {}).items()}
        self.positions.restore([Position.model_validate(p) for p in state.get("positions", [])])
        self._snapshots.clear()
        for snap in state.get("snapshots", []):
            self._snapshots.append(AccountSnapshot.model_validate(snap))

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
