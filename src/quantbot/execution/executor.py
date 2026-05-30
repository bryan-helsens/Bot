"""Risk-gated order execution.

:class:`OrderExecutor` is the *only* path from a trading signal to a live order.
It enforces the architectural invariant that every order is validated by the
risk engine first:

    signal → RiskEngine.evaluate → (approved?) → ExchangeGateway.create_order

A rejected proposal never reaches the exchange; it is logged, emits a risk
event, and returns ``None``. On approval the executor places the entry order,
registers it with the :class:`OrderManager`, opens the position in the
:class:`PositionManager`, and (best-effort) places the protective stop-loss
order. Protective take-profits are managed dynamically by the engine via the
:class:`~quantbot.risk.stops.StopManager` as price evolves.
"""

from __future__ import annotations

from decimal import Decimal

from quantbot.core.constants import OrderType, Side
from quantbot.core.events import Event, EventBus
from quantbot.core.constants import EventType
from quantbot.core.exceptions import ExchangeError, ExecutionError
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Order, Position, Signal, utcnow
from quantbot.exchanges.base import ExchangeGateway, OrderRequest
from quantbot.execution.order_manager import OrderManager
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import OrderProposal, RiskEngine


class OrderExecutor(LoggerMixin):
    """Execute risk-approved orders against an exchange gateway."""

    def __init__(
        self,
        gateway: ExchangeGateway,
        risk_engine: RiskEngine,
        portfolio: PortfolioManager,
        *,
        order_manager: OrderManager | None = None,
        event_bus: EventBus | None = None,
        commission_rate: Decimal = Decimal("0.001"),
    ) -> None:
        self._gateway = gateway
        self._risk = risk_engine
        self._portfolio = portfolio
        self._orders = order_manager or OrderManager()
        self._bus = event_bus
        self._commission_rate = commission_rate

    @property
    def orders(self) -> OrderManager:
        return self._orders

    # ------------------------------------------------------------------ entry

    async def execute_signal(self, signal: Signal, *, atr: Decimal | None = None) -> Position | None:
        """Validate *signal* through risk and, if approved, open the position."""
        proposal = await self._risk.evaluate(signal, self._portfolio.risk_view(), atr=atr)
        if proposal.rejected:
            await self._risk.emit_rejection(signal, _as_limit_check(proposal))
            self.log.info("signal_rejected", symbol=signal.symbol, reason=proposal.reason)
            return None
        return await self._open_from_proposal(proposal)

    async def _open_from_proposal(self, proposal: OrderProposal) -> Position | None:
        """Place the entry order and open the position from an approved proposal."""
        request = OrderRequest(
            symbol=proposal.symbol,
            side=proposal.side,
            type=OrderType.MARKET,
            quantity=proposal.quantity,
        )
        try:
            order = await self._gateway.create_order(request)
        except ExchangeError as exc:
            self.log.error("entry_order_failed", symbol=proposal.symbol, error=str(exc))
            raise ExecutionError(f"Entry order failed: {exc}") from exc

        self._orders.track(order)
        fill_price = order.avg_fill_price or proposal.price
        fee = fill_price * proposal.quantity * self._commission_rate

        position = self._portfolio.positions.open_position(
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=proposal.quantity,
            entry_price=fill_price,
            strategy=None,
            stop_loss=proposal.stop_loss,
            take_profit_levels=proposal.take_profit_levels,
            fee=fee,
            market=self._gateway.market,
        )
        # Cash moves only when PnL is realised (on close); the entry fee is
        # carried on the position and reflected in equity via unrealised PnL.

        await self._place_protective_stop(position)
        await self._emit(EventType.TRADE_OPENED, {
            "symbol": position.symbol,
            "side": position.side.value,
            "quantity": str(position.quantity),
            "entry_price": str(position.entry_price),
            "stop_loss": str(position.stop_loss) if position.stop_loss else None,
        })
        self.log.info(
            "position_executed", symbol=position.symbol, side=position.side.value,
            qty=float(position.quantity), entry=float(position.entry_price),
        )
        return position

    async def _place_protective_stop(self, position: Position) -> None:
        """Best-effort placement of the protective stop-loss order."""
        if position.stop_loss is None:
            return
        exit_side = Side.SELL if position.side.sign > 0 else Side.BUY
        request = OrderRequest(
            symbol=position.symbol,
            side=exit_side,
            type=OrderType.STOP_LOSS,
            quantity=position.quantity,
            stop_price=position.stop_loss,
            reduce_only=True,
        )
        try:
            stop_order = await self._gateway.create_order(request)
            self._orders.track(stop_order)
            position.meta["stop_order_id"] = stop_order.client_order_id
        except ExchangeError as exc:
            # Don't unwind the position on a stop-placement failure; log loudly so
            # monitoring catches it. The StopManager still enforces the stop
            # locally on each price tick as a backstop.
            self.log.error("stop_order_failed", symbol=position.symbol, error=str(exc))

    # ------------------------------------------------------------------ exit

    async def close_position(
        self, position: Position, *, exit_price: Decimal | None = None, reason=None
    ) -> Order | None:
        """Place a closing market order for *position* and cancel its stop."""
        from quantbot.core.constants import ExitReason

        reason = reason or ExitReason.SIGNAL
        exit_side = Side.SELL if position.side.sign > 0 else Side.BUY
        request = OrderRequest(
            symbol=position.symbol,
            side=exit_side,
            type=OrderType.MARKET,
            quantity=position.quantity,
            reduce_only=True,
        )
        try:
            order = await self._gateway.create_order(request)
        except ExchangeError as exc:
            self.log.error("close_order_failed", symbol=position.symbol, error=str(exc))
            raise ExecutionError(f"Close order failed: {exc}") from exc

        self._orders.track(order)
        await self._cancel_stop(position)

        fill_price = order.avg_fill_price or exit_price or position.entry_price
        fee = fill_price * position.quantity * self._commission_rate
        trade = self._portfolio.positions.close_position(
            position.symbol, exit_price=fill_price, reason=reason, fee=fee,
        )
        if trade is not None:
            self._portfolio.apply_trade(trade)
            self._risk.record_trade_result(position, trade.net_pnl)
            await self._emit(EventType.TRADE_CLOSED, {
                "symbol": trade.symbol,
                "net_pnl": str(trade.net_pnl),
                "exit_price": str(trade.exit_price),
                "reason": reason.value,
            })
        return order

    async def _cancel_stop(self, position: Position) -> None:
        stop_id = position.meta.get("stop_order_id")
        if not stop_id:
            return
        try:
            await self._gateway.cancel_order(position.symbol, client_order_id=str(stop_id))
        except ExchangeError as exc:
            self.log.warning("stop_cancel_failed", symbol=position.symbol, error=str(exc))

    # ------------------------------------------------------------------ helpers

    async def _emit(self, event_type: EventType, payload: dict) -> None:
        if self._bus is not None:
            await self._bus.publish(Event(event_type, payload={**payload, "ts": utcnow().isoformat()}, source="executor"))


def _as_limit_check(proposal: OrderProposal):
    """Adapt a rejected proposal into a LimitCheck for rejection emission."""
    from quantbot.risk.limits import LimitCheck

    return LimitCheck(False, proposal.event_type, proposal.reason)


__all__ = ["OrderExecutor"]
