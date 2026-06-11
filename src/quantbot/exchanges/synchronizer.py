"""Order & position reconciliation between local state and the exchange.

After a restart, a network partition, or any period where the bot missed
websocket user-events, local state can drift from the exchange's truth. The
:class:`OrderSynchronizer` reconciles them:

* Fetch open orders & positions from the exchange (the source of truth).
* Compare against the locally-tracked orders/positions.
* Produce a :class:`ReconciliationResult` describing the differences and the
  corrective actions taken (status updates, orphan detection, fills missed).

It never *places* new orders — reconciliation only updates local bookkeeping and
flags discrepancies for the engine/risk layer to act on. This keeps the
synchroniser safe to run automatically on every (re)connect.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quantbot.core.constants import OrderStatus
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Order, Position
from quantbot.exchanges.base import ExchangeGateway


@dataclass(slots=True)
class ReconciliationResult:
    """Summary of a reconciliation pass."""

    #: Local orders whose status changed to match the exchange.
    updated_orders: list[Order] = field(default_factory=list)
    #: Orders open locally but unknown/closed on the exchange (likely filled or
    #: cancelled while we were disconnected).
    closed_locally: list[Order] = field(default_factory=list)
    #: Orders open on the exchange that we had no local record of.
    orphan_orders: list[Order] = field(default_factory=list)
    #: Positions present on the exchange but not tracked locally.
    orphan_positions: list[Position] = field(default_factory=list)
    #: Positions tracked locally but absent on the exchange (closed remotely).
    stale_positions: list[Position] = field(default_factory=list)

    @property
    def has_discrepancies(self) -> bool:
        """Whether any difference was detected."""
        return bool(
            self.closed_locally
            or self.orphan_orders
            or self.orphan_positions
            or self.stale_positions
        )

    def summary(self) -> dict[str, int]:
        """Counts per category for logging/metrics."""
        return {
            "updated_orders": len(self.updated_orders),
            "closed_locally": len(self.closed_locally),
            "orphan_orders": len(self.orphan_orders),
            "orphan_positions": len(self.orphan_positions),
            "stale_positions": len(self.stale_positions),
        }


class OrderSynchronizer(LoggerMixin):
    """Reconcile locally-tracked orders/positions with the exchange."""

    def __init__(self, gateway: ExchangeGateway) -> None:
        self._gateway = gateway

    async def reconcile(
        self,
        local_orders: list[Order],
        local_positions: list[Position] | None = None,
        *,
        symbols: list[str] | None = None,
    ) -> ReconciliationResult:
        """Reconcile *local_orders*/*local_positions* against the exchange.

        Args:
            local_orders: Orders the bot believes are open.
            local_positions: Positions the bot believes are open (futures).
            symbols: Restrict the exchange query to these symbols (defaults to
                the union of symbols seen in the local state).

        Returns:
            A :class:`ReconciliationResult` describing detected differences. The
            *local* objects in ``updated_orders`` are mutated in place to the new
            status so callers can persist them directly.
        """
        local_positions = local_positions or []
        result = ReconciliationResult()

        exchange_orders = await self._fetch_open_orders(symbols)
        await self._reconcile_orders(local_orders, exchange_orders, result)
        await self._reconcile_positions(local_positions, symbols, result)

        if result.has_discrepancies:
            self.log.warning("reconciliation_discrepancies", **result.summary())
        else:
            self.log.info("reconciliation_clean", **result.summary())
        return result

    # ------------------------------------------------------------------ orders

    async def _fetch_open_orders(self, symbols: list[str] | None) -> dict[str, Order]:
        """Fetch open orders from the exchange keyed by exchange order id.

        Resilient per symbol: a symbol the exchange rejects (e.g. -1121 Invalid
        symbol for a coin not listed on the testnet) is logged and skipped so one
        bad symbol can't abort the whole reconciliation pass.
        """
        orders: list[Order] = []
        if symbols:
            for symbol in symbols:
                try:
                    orders.extend(await self._gateway.get_open_orders(symbol))
                except Exception as exc:  # noqa: BLE001 - skip bad symbol, keep the rest
                    self.log.warning(
                        "open_orders_fetch_skipped", symbol=symbol, error=str(exc)
                    )
        else:
            orders.extend(await self._gateway.get_open_orders())
        return {self._key(o): o for o in orders}

    async def _reconcile_orders(
        self,
        local_orders: list[Order],
        exchange_orders: dict[str, Order],
        result: ReconciliationResult,
    ) -> None:
        seen_keys: set[str] = set()
        for local in local_orders:
            key = self._key(local)
            seen_keys.add(key)
            remote = exchange_orders.get(key)
            if remote is None:
                # Not open on the exchange anymore — fetch its terminal state.
                await self._resolve_missing(local, result)
                continue
            if remote.status != local.status or remote.filled_qty != local.filled_qty:
                local.status = remote.status
                local.filled_qty = remote.filled_qty
                local.avg_fill_price = remote.avg_fill_price
                local.touch()
                result.updated_orders.append(local)

        for key, remote in exchange_orders.items():
            if key not in seen_keys:
                result.orphan_orders.append(remote)

    async def _resolve_missing(self, local: Order, result: ReconciliationResult) -> None:
        """Determine the terminal state of a locally-open, remotely-absent order."""
        try:
            remote = await self._gateway.get_order(
                local.symbol,
                order_id=local.exchange_order_id,
                client_order_id=local.client_order_id,
            )
        except Exception as exc:  # noqa: BLE001 - treat lookup failure as closed/unknown
            self.log.warning(
                "order_lookup_failed", order=local.client_order_id, error=str(exc)
            )
            local.status = OrderStatus.CANCELED
            local.touch()
            result.closed_locally.append(local)
            return
        local.status = remote.status
        local.filled_qty = remote.filled_qty
        local.avg_fill_price = remote.avg_fill_price
        local.touch()
        result.closed_locally.append(local)

    # ------------------------------------------------------------------ positions

    async def _reconcile_positions(
        self,
        local_positions: list[Position],
        symbols: list[str] | None,
        result: ReconciliationResult,
    ) -> None:
        exchange_positions = await self._gateway.get_positions()
        remote_by_symbol = {p.symbol: p for p in exchange_positions}
        local_by_symbol = {p.symbol: p for p in local_positions}

        for symbol, remote in remote_by_symbol.items():
            if symbol not in local_by_symbol:
                result.orphan_positions.append(remote)

        for symbol, local in local_by_symbol.items():
            if symbol not in remote_by_symbol:
                result.stale_positions.append(local)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _key(order: Order) -> str:
        """Stable identity for matching orders across local/remote state."""
        return order.exchange_order_id or order.client_order_id


__all__ = ["OrderSynchronizer", "ReconciliationResult"]
