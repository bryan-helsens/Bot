"""Position lifecycle management.

:class:`PositionManager` owns the set of open positions and turns fills into
position state: opening, scaling in (bounded averaging), partial take-profit
exits, and full closes. Closing (fully or partially) produces a realised
:class:`~quantbot.core.models.Trade` with correct fee-aware PnL.

It is pure domain logic — no exchange or persistence calls — so it behaves
identically live and in the backtester. The execution layer feeds it fills and
persists the trades it returns.
"""

from __future__ import annotations

from decimal import Decimal

from quantbot.core.constants import ExitReason, PositionSide, PositionStatus, Side
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Position, TakeProfitLevel, Trade, utcnow


class PositionManager(LoggerMixin):
    """Manage open positions and realise trades on close."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    # ------------------------------------------------------------------ access

    def get(self, symbol: str) -> Position | None:
        """Return the open position for *symbol*, if any."""
        return self._positions.get(symbol)

    def all_open(self) -> list[Position]:
        """All currently-open positions."""
        return [p for p in self._positions.values() if p.is_open]

    def has_position(self, symbol: str) -> bool:
        return symbol in self._positions and self._positions[symbol].is_open

    @property
    def open_count(self) -> int:
        return len(self.all_open())

    # ------------------------------------------------------------------ open / scale

    def open_position(
        self,
        *,
        symbol: str,
        side: Side,
        quantity: Decimal,
        entry_price: Decimal,
        strategy: str | None = None,
        stop_loss: Decimal | None = None,
        take_profit_levels: list[TakeProfitLevel] | None = None,
        leverage: int = 1,
        fee: Decimal = Decimal("0"),
        market=None,
    ) -> Position:
        """Open a new position (or scale into an existing one on the same side)."""
        existing = self.get(symbol)
        if existing is not None and existing.is_open:
            return self._scale_in(existing, side, quantity, entry_price, fee)

        position_side = PositionSide.from_side(side)
        position = Position(
            strategy=strategy,
            symbol=symbol,
            side=position_side,
            status=PositionStatus.OPEN,
            quantity=quantity,
            entry_price=entry_price,
            mark_price=entry_price,
            stop_loss=stop_loss,
            take_profit_levels=take_profit_levels or [],
            leverage=leverage,
            fees_paid=fee,
            averaging_entries=1,
            meta={"last_entry_size": str(quantity)},
        )
        if market is not None:
            position.market = market
        self._positions[symbol] = position
        self.log.info(
            "position_opened", symbol=symbol, side=position_side.value,
            qty=float(quantity), entry=float(entry_price),
        )
        return position

    def _scale_in(
        self, position: Position, side: Side, quantity: Decimal, price: Decimal, fee: Decimal
    ) -> Position:
        """Average into an existing position (bounded by the risk engine upstream)."""
        if PositionSide.from_side(side) is not position.side:
            raise ValueError("Cannot scale in on the opposite side; close first")
        total_qty = position.quantity + quantity
        # New volume-weighted average entry price.
        position.entry_price = (
            position.entry_price * position.quantity + price * quantity
        ) / total_qty
        position.quantity = total_qty
        position.fees_paid += fee
        position.averaging_entries += 1
        position.meta["last_entry_size"] = str(quantity)
        self.log.info(
            "position_scaled_in", symbol=position.symbol,
            qty=float(quantity), new_avg=float(position.entry_price),
            entries=position.averaging_entries,
        )
        return position

    # ------------------------------------------------------------------ close

    def close_position(
        self,
        symbol: str,
        *,
        exit_price: Decimal,
        reason: ExitReason = ExitReason.SIGNAL,
        fee: Decimal = Decimal("0"),
        bars_held: int | None = None,
    ) -> Trade | None:
        """Fully close *symbol* and return the realised :class:`Trade`."""
        position = self.get(symbol)
        if position is None or not position.is_open:
            return None
        trade = self._realise(position, position.quantity, exit_price, reason, fee, bars_held)
        position.status = PositionStatus.CLOSED
        position.exit_price = exit_price
        position.closed_at = utcnow()
        position.realized_pnl += trade.net_pnl
        del self._positions[symbol]
        self.log.info(
            "position_closed", symbol=symbol, reason=reason.value,
            exit=float(exit_price), net_pnl=float(trade.net_pnl),
        )
        return trade

    def reduce_position(
        self,
        symbol: str,
        *,
        fraction: Decimal,
        exit_price: Decimal,
        reason: ExitReason = ExitReason.TAKE_PROFIT,
        fee: Decimal = Decimal("0"),
        tp_index: int | None = None,
    ) -> Trade | None:
        """Partially close *fraction* of *symbol* (e.g. a take-profit rung).

        If the fraction closes (≈) the whole position, it is fully closed.
        """
        position = self.get(symbol)
        if position is None or not position.is_open:
            return None
        fraction = max(Decimal("0"), min(Decimal("1"), fraction))
        close_qty = position.quantity * fraction
        if close_qty <= 0:
            return None
        remaining = position.quantity - close_qty
        if remaining <= position.entry_price * 0:  # i.e. remaining <= 0
            return self.close_position(symbol, exit_price=exit_price, reason=reason, fee=fee)

        trade = self._realise(position, close_qty, exit_price, reason, fee, None)
        position.quantity = remaining
        position.realized_pnl += trade.net_pnl
        position.fees_paid += fee
        if tp_index is not None and 0 <= tp_index < len(position.take_profit_levels):
            position.take_profit_levels[tp_index].triggered = True
        self.log.info(
            "position_reduced", symbol=symbol, fraction=float(fraction),
            qty=float(close_qty), net_pnl=float(trade.net_pnl), remaining=float(remaining),
        )
        return trade

    # ------------------------------------------------------------------ updates

    def update_mark_price(self, symbol: str, price: Decimal) -> None:
        """Update the mark price used for unrealised PnL."""
        position = self.get(symbol)
        if position is not None and position.is_open:
            position.mark_price = price

    def update_stop(self, symbol: str, stop_loss: Decimal) -> None:
        position = self.get(symbol)
        if position is not None and position.is_open:
            position.stop_loss = stop_loss

    def update_trailing_stop(self, symbol: str, trailing: Decimal) -> None:
        position = self.get(symbol)
        if position is not None and position.is_open:
            position.trailing_stop_price = trailing

    def arm_break_even(self, symbol: str) -> None:
        position = self.get(symbol)
        if position is not None and position.is_open:
            position.break_even_armed = True

    # ------------------------------------------------------------------ metrics

    def total_unrealized_pnl(self, prices: dict[str, Decimal] | None = None) -> Decimal:
        """Sum of unrealised PnL across open positions at current/given prices."""
        total = Decimal("0")
        for position in self.all_open():
            price = (prices or {}).get(position.symbol, position.mark_price)
            total += position.unrealized_pnl(price)
        return total

    def total_exposure(self, prices: dict[str, Decimal] | None = None) -> Decimal:
        """Sum of position notionals across open positions."""
        total = Decimal("0")
        for position in self.all_open():
            price = (prices or {}).get(position.symbol, position.mark_price)
            total += position.notional(price)
        return total

    # ------------------------------------------------------------------ internal

    def _realise(
        self,
        position: Position,
        quantity: Decimal,
        exit_price: Decimal,
        reason: ExitReason,
        fee: Decimal,
        bars_held: int | None,
    ) -> Trade:
        """Create a realised Trade for *quantity* of *position* at *exit_price*."""
        # Allocate a proportional share of the entry fees to this closed quantity.
        entry_fee_share = (
            position.fees_paid * (quantity / position.quantity) if position.quantity > 0 else Decimal("0")
        )
        return Trade(
            position_id=position.id,
            strategy=position.strategy,
            symbol=position.symbol,
            side=position.side,
            quantity=quantity,
            entry_price=position.entry_price,
            exit_price=exit_price,
            fees=entry_fee_share + fee,
            exit_reason=reason,
            bars_held=bars_held,
            opened_at=position.opened_at,
        )


__all__ = ["PositionManager"]
