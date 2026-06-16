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

import asyncio
from decimal import Decimal

from quantbot.core.constants import MarketType, OrderType, Side
from quantbot.core.events import Event, EventBus
from quantbot.core.constants import EventType
from quantbot.core.exceptions import ExchangeError, ExecutionError
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Order, Position, Signal, utcnow
from quantbot.exchanges.base import ExchangeGateway, OrderRequest
from quantbot.execution.order_manager import OrderManager
from quantbot.portfolio.manager import PortfolioManager
from quantbot.risk.engine import OrderProposal, RiskEngine


class _OrderRateLimiter:
    """Space out NEW-order submissions to stay under the exchange rate limit.

    Binance rejects bursts with ``-1015 Too many new orders`` (50 per 10s). When
    many candles close together the bot can fire dozens of entries+stops at once;
    without spacing, some protective stops fail to place and a position runs
    unprotected. This serialises submissions to at most one per ``min_interval``.
    """

    def __init__(self, min_interval: float = 0.22) -> None:
        self._min_interval = min_interval
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = loop.time()
            self._next_at = now + self._min_interval


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
        self._rate_limiter = _OrderRateLimiter()

    async def _submit_order(self, request: OrderRequest) -> Order:
        """Place a NEW order through the rate limiter (avoids -1015 bursts)."""
        await self._rate_limiter.acquire()
        return await self._gateway.create_order(request)

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
        proposal = await self._enforce_min_notional(proposal)
        if proposal is None:
            return None
        return await self._open_from_proposal(proposal, strategy=signal.strategy)

    async def _enforce_min_notional(self, proposal: OrderProposal) -> OrderProposal | None:
        """Keep an entry order at/above the exchange minimum notional.

        On small accounts the risk-sized order can fall below the exchange's
        MIN_NOTIONAL and be rejected. Bump it up to the minimum (the smallest valid
        order — a negligible risk increase) when affordable, otherwise skip the
        trade cleanly with a clear log instead of letting the exchange reject it.
        """
        try:
            info = await self._gateway.get_symbol_info(proposal.symbol)
        except Exception:  # noqa: BLE001 - can't check -> proceed and let the exchange decide
            return proposal
        min_notional = getattr(info, "min_notional", Decimal("0"))
        if min_notional <= 0 or proposal.price <= 0 or proposal.quantity <= 0:
            return proposal
        notional = proposal.quantity * proposal.price
        if notional >= min_notional:
            return proposal
        target = min_notional * Decimal("1.01")  # small buffer for fees/rounding
        bumped_qty = target / proposal.price
        if bumped_qty * proposal.price > self._portfolio.cash:
            self.log.warning(
                "order_below_min_notional_skipped", symbol=proposal.symbol,
                notional=float(notional), min_notional=float(min_notional),
            )
            return None
        self.log.info(
            "order_bumped_to_min_notional", symbol=proposal.symbol,
            from_notional=float(notional), to_notional=float(bumped_qty * proposal.price),
        )
        proposal.quantity = bumped_qty
        return proposal

    async def _open_from_proposal(
        self, proposal: OrderProposal, *, strategy: str | None = None
    ) -> Position | None:
        """Place the entry order and open the position from an approved proposal."""
        request = OrderRequest(
            symbol=proposal.symbol,
            side=proposal.side,
            type=OrderType.MARKET,
            quantity=proposal.quantity,
        )
        try:
            order = await self._submit_order(request)
        except ExchangeError as exc:
            self.log.error("entry_order_failed", symbol=proposal.symbol, error=str(exc))
            raise ExecutionError(f"Entry order failed: {exc}") from exc

        self._orders.track(order)
        fill_price = order.avg_fill_price or proposal.price
        # Record the ACTUAL filled quantity, not the requested one. On a thin pair
        # the exchange may fill less than asked; recording the request would make the
        # bot think it holds more than it does (and later fail to sell it).
        filled_qty = order.filled_qty if order.filled_qty and order.filled_qty > 0 else proposal.quantity
        fee = fill_price * filled_qty * self._commission_rate

        position = self._portfolio.positions.open_position(
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=filled_qty,
            entry_price=fill_price,
            strategy=strategy,
            stop_loss=proposal.stop_loss,
            take_profit_levels=proposal.take_profit_levels,
            fee=fee,
            market=self._gateway.market,
        )
        # Cash moves only when PnL is realised (on close); the entry fee is
        # carried on the position and reflected in equity via unrealised PnL.

        # On LIVE spot, verify the booked quantity against the real account balance
        # and correct it. On thin meme pairs the exchange can fill far less than
        # asked; without this the books inflate (phantom holding -> inflated equity
        # -> ever-bigger buys -> can't sell -> NOTIONAL errors).
        await self._verify_spot_fill(position)
        position = self._portfolio.positions.get(proposal.symbol)
        if position is None or not position.is_open:
            self.log.warning("entry_dropped_no_fill", symbol=proposal.symbol)
            return None

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

    async def _verify_spot_fill(self, position: Position) -> None:
        """Correct a spot position's quantity to the actual account balance.

        Only for a real spot gateway (skipped for the paper broker, whose base
        balance is always 0). If we hold far less of the base asset than the books
        say, the order under-filled — correct the quantity (or drop the position if
        nothing filled) so the books match reality.
        """
        from quantbot.engine.paper_broker import PaperTradingBroker

        if getattr(self._gateway, "market", None) is not MarketType.SPOT:
            return
        if isinstance(self._gateway, PaperTradingBroker):
            return
        try:
            info = await self._gateway.get_symbol_info(position.symbol)
            bal = await self._gateway.get_balance(info.base_asset)
            held = bal.free + bal.locked
        except Exception as exc:  # noqa: BLE001 - best-effort; leave books as-is
            self.log.warning("spot_fill_verify_skipped", symbol=position.symbol, error=str(exc))
            return
        if held >= position.quantity * Decimal("0.9"):
            return  # books match reality (within 10%)
        if held <= 0:
            self.log.warning("spot_fill_none_dropping", symbol=position.symbol,
                             booked=float(position.quantity))
            self._portfolio.positions.close_position(
                position.symbol, exit_price=position.entry_price, fee=Decimal("0"),
            )
            return
        self.log.warning("spot_fill_corrected", symbol=position.symbol,
                         booked=float(position.quantity), actual=float(held))
        position.quantity = held

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
            stop_order = await self._submit_order(request)
            self._orders.track(stop_order)
            position.meta["stop_order_id"] = stop_order.client_order_id
        except ExchangeError as exc:
            # Don't unwind the position on a stop-placement failure; log loudly so
            # monitoring catches it. The StopManager still enforces the stop
            # locally on each price tick as a backstop.
            self.log.error("stop_order_failed", symbol=position.symbol, error=str(exc))

    # ------------------------------------------------------------------ partial exit

    async def reduce_position(
        self, position: Position, *, fraction: Decimal, exit_price: Decimal | None = None,
        reason=None, tp_index: int | None = None,
    ) -> Order | None:
        """Place a partial reduce (e.g. a take-profit rung) and update the books.

        Mirrors :meth:`close_position` but for a fraction of the position. Crucially
        it places a *real* reduce-only order through the gateway before updating the
        internal position — the engine must never reduce its books without the
        matching exchange order, or the bot's view and the real holding diverge.
        """
        from quantbot.core.constants import ExitReason

        reason = reason or ExitReason.TAKE_PROFIT
        fraction = max(Decimal("0"), min(Decimal("1"), fraction))
        close_qty = position.quantity * fraction
        if close_qty <= 0:
            return None
        exit_side = Side.SELL if position.side.sign > 0 else Side.BUY
        request = OrderRequest(
            symbol=position.symbol, side=exit_side, type=OrderType.MARKET,
            quantity=close_qty, reduce_only=True,
        )
        # Cancel the resting protective stop FIRST — on spot it locks the base asset
        # and the reduce sell would otherwise fail with -2010 (insufficient free
        # balance). A fresh stop for the remaining quantity is placed below.
        await self._cancel_stop(position)
        position.meta.pop("stop_order_id", None)
        try:
            order = await self._submit_order(request)
        except ExchangeError as exc:
            if _is_dust_error(exc):
                # The slice to take profit on is too small to trade — keep the whole
                # position and re-place its protective stop; skip this rung.
                self.log.warning("reduce_skipped_dust", symbol=position.symbol, error=str(exc))
                await self._place_protective_stop(position)
                return None
            self.log.error("reduce_order_failed", symbol=position.symbol, error=str(exc))
            raise ExecutionError(f"Reduce order failed: {exc}") from exc

        self._orders.track(order)
        fill_price = order.avg_fill_price or exit_price or position.entry_price
        fee = fill_price * close_qty * self._commission_rate
        trade = self._portfolio.positions.reduce_position(
            position.symbol, fraction=fraction, exit_price=fill_price, reason=reason,
            fee=fee, tp_index=tp_index,
        )
        if trade is not None:
            self._portfolio.apply_trade(trade)
            self._risk.record_trade_result(position, trade.net_pnl)
            held = self._portfolio.positions.get(position.symbol)
            if held is not None and held.is_open:
                await self._place_protective_stop(held)  # fresh stop for the remainder
            # (the old stop was already cancelled above)
            await self._emit(EventType.TRADE_CLOSED, {
                "symbol": trade.symbol,
                "net_pnl": str(trade.net_pnl),
                "exit_price": str(trade.exit_price),
                "reason": reason.value,
                "partial": True,
            })
        return order

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
        # Cancel the resting protective stop FIRST. On spot it locks the base asset,
        # so selling to close before cancelling fails with -2010 (insufficient free
        # balance — it's reserved by the stop order).
        await self._cancel_stop(position)
        try:
            order = await self._submit_order(request)
        except ExchangeError as exc:
            if _is_dust_error(exc):
                # The remaining holding is too small to sell (below the exchange's
                # minimum). Close it in the books at the mark price so the bot stops
                # retrying every candle; the unsellable dust stays on the account.
                self.log.warning("closed_locally_dust", symbol=position.symbol, error=str(exc))
                await self._finalise_close(position, exit_price or position.entry_price, reason)
                return None
            self.log.error("close_order_failed", symbol=position.symbol, error=str(exc))
            raise ExecutionError(f"Close order failed: {exc}") from exc

        self._orders.track(order)

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

    async def _finalise_close(self, position: Position, fill_price: Decimal, reason) -> None:
        """Close a position in the books only (no exchange order) — used for dust."""
        trade = self._portfolio.positions.close_position(
            position.symbol, exit_price=fill_price, reason=reason, fee=Decimal("0"),
        )
        if trade is not None:
            self._portfolio.apply_trade(trade)
            self._risk.record_trade_result(position, trade.net_pnl)
            await self._emit(EventType.TRADE_CLOSED, {
                "symbol": trade.symbol, "net_pnl": str(trade.net_pnl),
                "exit_price": str(trade.exit_price), "reason": reason.value, "dust": True,
            })

    async def apply_external_close(
        self, position: Position, *, fill_price: Decimal, fee: Decimal = Decimal("0"), reason=None
    ) -> None:
        """Reflect an exchange-side close (e.g. a resting stop that fired) locally.

        The exchange has ALREADY closed the position, so this places NO order — it
        only realises the trade in the books so the bot stops managing a position
        that no longer exists. Used by the user-stream/reconciliation path.
        """
        from quantbot.core.constants import ExitReason

        reason = reason or ExitReason.STOP_LOSS
        trade = self._portfolio.positions.close_position(
            position.symbol, exit_price=fill_price, reason=reason, fee=fee,
        )
        if trade is not None:
            self._portfolio.apply_trade(trade)
            self._risk.record_trade_result(position, trade.net_pnl)
            await self._emit(EventType.TRADE_CLOSED, {
                "symbol": trade.symbol, "net_pnl": str(trade.net_pnl),
                "exit_price": str(trade.exit_price), "reason": reason.value,
                "external": True,
            })
            self.log.info(
                "external_close_reconciled", symbol=position.symbol,
                exit=float(fill_price), net_pnl=float(trade.net_pnl),
            )

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


def _is_dust_error(exc: ExchangeError) -> bool:
    """Whether an order failed because the amount is too small to trade (dust)."""
    code = getattr(exc, "code", None)
    msg = str(exc).upper()
    return code in (-1013,) or "NOTIONAL" in msg or "LOT_SIZE" in msg or "MIN_NOTIONAL" in msg


__all__ = ["OrderExecutor"]
