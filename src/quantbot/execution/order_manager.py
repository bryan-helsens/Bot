"""Order lifecycle tracking (a small state machine).

:class:`OrderManager` keeps the authoritative local view of every order the bot
has submitted, applying valid status transitions as exchange updates arrive
(from REST polling or the user-data websocket). It rejects illegal transitions
(e.g. a FILLED order going back to NEW), tracks fills, and exposes queries for
open orders so the rest of the system never has to scan raw exchange responses.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from quantbot.core.constants import OrderStatus
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Order

# Legal status transitions. A terminal status accepts no further transitions.
_VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {
        OrderStatus.NEW, OrderStatus.REJECTED, OrderStatus.FILLED,
        OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELED, OrderStatus.EXPIRED,
    },
    OrderStatus.NEW: {
        OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED,
        OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED,
        OrderStatus.CANCELED, OrderStatus.EXPIRED,
    },
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.EXPIRED: set(),
}


class OrderManager(LoggerMixin):
    """Track local order state and apply exchange updates safely."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}  # keyed by client_order_id
        self._by_exchange_id: dict[str, str] = {}  # exchange_id -> client_order_id

    # ------------------------------------------------------------------ register

    def track(self, order: Order) -> Order:
        """Begin tracking a newly-submitted order."""
        self._orders[order.client_order_id] = order
        if order.exchange_order_id:
            self._by_exchange_id[order.exchange_order_id] = order.client_order_id
        return order

    def get(self, *, client_order_id: str | None = None, exchange_order_id: str | None = None) -> Order | None:
        """Look up a tracked order by client or exchange id."""
        if client_order_id is not None:
            return self._orders.get(client_order_id)
        if exchange_order_id is not None:
            coid = self._by_exchange_id.get(exchange_order_id)
            return self._orders.get(coid) if coid else None
        return None

    # ------------------------------------------------------------------ updates

    def apply_update(self, update: Order) -> Order | None:
        """Merge an exchange order update into the tracked order.

        Matches on client/exchange id, validates the status transition and
        updates fill quantities. Returns the updated local order, or ``None`` if
        the order is not tracked or the transition is illegal.
        """
        local = self.get(
            client_order_id=update.client_order_id,
            exchange_order_id=update.exchange_order_id,
        )
        if local is None:
            return None

        if update.exchange_order_id and not local.exchange_order_id:
            local.exchange_order_id = update.exchange_order_id
            self._by_exchange_id[update.exchange_order_id] = local.client_order_id

        if update.status != local.status:
            allowed = _VALID_TRANSITIONS.get(local.status, set())
            if update.status not in allowed:
                self.log.warning(
                    "illegal_order_transition",
                    order=local.client_order_id,
                    from_status=local.status.value,
                    to_status=update.status.value,
                )
                return None
            local.status = update.status

        # Fills only ever move forward.
        if update.filled_qty > local.filled_qty:
            local.filled_qty = update.filled_qty
        if update.avg_fill_price is not None:
            local.avg_fill_price = update.avg_fill_price
        if update.commission > 0:
            local.commission = update.commission
        local.touch()

        if local.status.is_terminal:
            self.log.debug("order_terminal", order=local.client_order_id, status=local.status.value)
        return local

    def mark_filled(self, client_order_id: str, *, fill_price: Decimal, filled_qty: Decimal) -> Order | None:
        """Convenience: mark an order fully filled (used by the paper broker)."""
        order = self._orders.get(client_order_id)
        if order is None:
            return None
        order.status = OrderStatus.FILLED
        order.filled_qty = filled_qty
        order.avg_fill_price = fill_price
        order.touch()
        return order

    # ------------------------------------------------------------------ queries

    def open_orders(self, symbol: str | None = None) -> list[Order]:
        return [
            o for o in self._orders.values()
            if o.is_open and (symbol is None or o.symbol == symbol)
        ]

    def all_orders(self) -> list[Order]:
        return list(self._orders.values())

    def remove_terminal(self) -> int:
        """Drop terminal orders from tracking; return how many were removed."""
        terminal = [coid for coid, o in self._orders.items() if o.status.is_terminal]
        for coid in terminal:
            order = self._orders.pop(coid)
            if order.exchange_order_id:
                self._by_exchange_id.pop(order.exchange_order_id, None)
        return len(terminal)

    def reconcile(self, exchange_orders: Iterable[Order]) -> None:
        """Apply a batch of exchange order states (used after reconnect)."""
        for order in exchange_orders:
            if self.get(client_order_id=order.client_order_id, exchange_order_id=order.exchange_order_id):
                self.apply_update(order)
            else:
                self.track(order)


__all__ = ["OrderManager"]
