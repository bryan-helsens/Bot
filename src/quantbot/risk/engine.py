"""The RiskEngine — the single, non-bypassable gate before any order.

Every order proposal (from a strategy signal, the aggregator or the AI module)
must pass :meth:`RiskEngine.evaluate`. The engine:

1. Rejects immediately if the emergency shutdown or circuit breaker is active.
2. Sizes the position (fixed/risk/Kelly/volatility) from current equity.
3. Validates against every limit: open trades, exposure (coin & portfolio),
   daily/weekly loss, drawdown, correlation, and the anti-martingale/averaging
   rules.
4. Computes protective levels (stop-loss + take-profit ladder).
5. Returns an :class:`OrderProposal` that is APPROVED, ADJUSTED (smaller size) or
   REJECTED — never a raw "yes". Rejections and adjustments emit risk events for
   the audit log and notifications.

No other component is permitted to create orders directly; this guarantees the
risk rules can never be circumvented by a strategy or AI signal.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from quantbot.core.config import RiskSettings, get_settings
from quantbot.core.constants import (
    PositionSide,
    RiskDecision,
    RiskEventType,
    Side,
)
from quantbot.core.events import Event, EventBus
from quantbot.core.constants import EventType
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Position, Signal, TakeProfitLevel, utcnow
from quantbot.risk.circuit_breaker import CircuitBreaker, EmergencyShutdown
from quantbot.risk.correlation import CorrelationMonitor
from quantbot.risk.limits import LimitCheck, LimitChecker
from quantbot.risk.position_sizing import PositionSizer, SizingInput, SizingResult
from quantbot.risk.stops import StopManager


@dataclass(slots=True)
class PortfolioView:
    """The snapshot of portfolio state the risk engine needs to decide."""

    equity: Decimal
    available_balance: Decimal
    open_positions: list[Position] = field(default_factory=list)

    def coin_notional(self, symbol: str) -> Decimal:
        return sum(
            (p.notional() for p in self.open_positions if p.symbol == symbol),
            Decimal("0"),
        )

    def total_notional(self) -> Decimal:
        return sum((p.notional() for p in self.open_positions), Decimal("0"))

    def position_for(self, symbol: str) -> Position | None:
        for p in self.open_positions:
            if p.symbol == symbol and p.is_open:
                return p
        return None

    @property
    def open_count(self) -> int:
        return sum(1 for p in self.open_positions if p.is_open)


@dataclass(slots=True)
class OrderProposal:
    """The risk engine's verdict on a proposed order."""

    decision: RiskDecision
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    stop_loss: Decimal | None = None
    take_profit_levels: list[TakeProfitLevel] = field(default_factory=list)
    risk_amount: Decimal = Decimal("0")
    reason: str = ""
    sizing: SizingResult | None = None
    event_type: RiskEventType | None = None

    @property
    def approved(self) -> bool:
        """Whether the order may be placed (approved or adjusted)."""
        return self.decision in (RiskDecision.APPROVED, RiskDecision.ADJUSTED)

    @property
    def rejected(self) -> bool:
        return self.decision is RiskDecision.REJECTED


class RiskEngine(LoggerMixin):
    """Central risk-management pipeline."""

    def __init__(
        self,
        settings: RiskSettings | None = None,
        *,
        event_bus: EventBus | None = None,
        win_rate: float = 0.5,
        win_loss_ratio: float = 1.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._cfg = settings or get_settings().risk
        self._bus = event_bus
        self.sizer = PositionSizer(self._cfg)
        self.limits = LimitChecker(self._cfg)
        self.correlation = CorrelationMonitor(self._cfg)
        # In a backtest, wall-clock time does not advance, so a wall-clock
        # circuit-breaker cooldown would never expire and would freeze the rest
        # of the run. Callers (the backtester) inject a *simulation clock* driven
        # by candle time so cooldowns elapse correctly.
        self.circuit_breaker = CircuitBreaker(
            self._cfg, time_fn=clock if clock is not None else time.monotonic
        )
        self.emergency = EmergencyShutdown()
        self.stops = StopManager(self._cfg)
        # Rolling trade statistics used for Kelly sizing.
        self._win_rate = win_rate
        self._win_loss_ratio = win_loss_ratio

    # ------------------------------------------------------------------ main API

    async def evaluate(
        self,
        signal: Signal,
        portfolio: PortfolioView,
        *,
        atr: Decimal | None = None,
    ) -> OrderProposal:
        """Validate and size *signal* against *portfolio*; return a verdict."""
        symbol = signal.symbol
        side = signal.side
        price = signal.price

        # 0. Global kill switches first — never trade while these are active.
        for gate in (self.emergency.check(), self.circuit_breaker.check()):
            if not gate.passed:
                return self._reject(signal, gate)

        # 1. Size the position from current equity.
        sizing = self.sizer.size(
            SizingInput(
                equity=portfolio.equity,
                price=price,
                stop_loss=signal.stop_loss,
                atr=atr,
                win_rate=self._win_rate,
                win_loss_ratio=self._win_loss_ratio,
            )
        )
        if sizing.quantity <= 0:
            return self._reject(
                signal,
                LimitCheck.fail(RiskEventType.ORDER_REJECTED, f"Sizing produced zero quantity ({sizing.reason})"),
            )

        # 2. Averaging / martingale rules (if adding to an existing position).
        existing = portfolio.position_for(symbol)
        last_size = Decimal(str(existing.meta.get("last_entry_size", existing.quantity))) if existing else Decimal("0")
        avg_check = self.limits.check_averaging(existing, sizing.quantity, last_size)
        if not avg_check.passed:
            return self._reject(signal, avg_check)

        # 3. Aggregate limit checks (exposure, losses, drawdown, open trades).
        new_notional = sizing.notional
        limit_check = self.limits.check_new_position(
            symbol=symbol,
            new_notional=new_notional,
            existing_coin_notional=portfolio.coin_notional(symbol),
            total_portfolio_notional=portfolio.total_notional(),
            equity=portfolio.equity,
            open_count=portfolio.open_count,
        )
        if not limit_check.passed:
            return self._reject(signal, limit_check)

        # 4. Correlation control against currently-held symbols.
        held = [p.symbol for p in portfolio.open_positions if p.is_open and p.symbol != symbol]
        corr_check = self.correlation.check(symbol, held)
        if not corr_check.passed:
            return self._reject(signal, corr_check)

        # 5. Protective levels.
        position_side = PositionSide.from_side(side)
        stop_loss, ladder = self.stops.initial_levels(
            position_side,
            price,
            stop_pct=self._stop_pct_from_signal(signal, position_side),
        )

        decision = RiskDecision.ADJUSTED if "capped" in sizing.reason else RiskDecision.APPROVED
        proposal = OrderProposal(
            decision=decision,
            symbol=symbol,
            side=side,
            quantity=sizing.quantity,
            price=price,
            stop_loss=signal.stop_loss or stop_loss,
            take_profit_levels=ladder,
            risk_amount=sizing.risk_amount,
            reason=sizing.reason,
            sizing=sizing,
        )
        await self._emit_decision(signal, proposal)
        return proposal

    # ------------------------------------------------------------------ feedback

    def record_trade_result(self, position: Position, pnl: Decimal) -> None:
        """Feed a closed trade back into the risk state (windows, breaker, stats)."""
        self.limits.record_trade_pnl(pnl)
        self.circuit_breaker.record_trade(pnl)
        self._update_win_stats(pnl)

    def update_equity(self, equity: Decimal) -> None:
        """Update equity-derived state (drawdown high-water mark)."""
        self.limits.update_equity(equity)
        if self.limits.current_drawdown(equity) >= self._cfg.max_drawdown and self._cfg.emergency_stop_enabled:
            self.emergency.trigger(f"max_drawdown {self.limits.current_drawdown(equity):.2%}")

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Feed a price to the correlation monitor."""
        self.correlation.update_price(symbol, price)

    def set_starting_equity(self, equity: Decimal) -> None:
        self.limits.set_starting_equity(equity)
        self.limits.update_equity(equity)

    # ------------------------------------------------------------------ helpers

    def _stop_pct_from_signal(self, signal: Signal, side: PositionSide) -> Decimal | None:
        if signal.stop_loss is None or signal.price <= 0:
            return None
        return abs(signal.price - signal.stop_loss) / signal.price

    def _update_win_stats(self, pnl: Decimal) -> None:
        """Exponentially-smoothed win rate and win/loss ratio for Kelly sizing."""
        alpha = 0.05
        win = 1.0 if pnl > 0 else 0.0
        self._win_rate = (1 - alpha) * self._win_rate + alpha * win
        magnitude = abs(float(pnl))
        if magnitude > 0:
            prev = self._win_loss_ratio
            target = magnitude if pnl > 0 else 1.0 / max(magnitude, 1e-9)
            # Keep the ratio in a sane band to avoid Kelly blow-ups.
            self._win_loss_ratio = max(0.1, min(5.0, (1 - alpha) * prev + alpha * min(target, 5.0)))

    def _reject(self, signal: Signal, check: LimitCheck) -> OrderProposal:
        proposal = OrderProposal(
            decision=RiskDecision.REJECTED,
            symbol=signal.symbol,
            side=signal.side,
            quantity=Decimal("0"),
            price=signal.price,
            reason=check.reason,
            event_type=check.event_type,
        )
        self.log.warning("risk_rejected", symbol=signal.symbol, reason=check.reason)
        return proposal

    async def _emit_decision(self, signal: Signal, proposal: OrderProposal) -> None:
        if self._bus is None:
            return
        await self._bus.publish(
            Event(
                EventType.RISK_EVENT,
                payload={
                    "decision": proposal.decision.value,
                    "symbol": signal.symbol,
                    "quantity": str(proposal.quantity),
                    "reason": proposal.reason,
                    "ts": utcnow().isoformat(),
                },
                source="risk_engine",
            )
        )

    async def emit_rejection(self, signal: Signal, check: LimitCheck) -> None:
        """Publish a rejection risk-event (call after :meth:`evaluate` rejects)."""
        if self._bus is None or check.event_type is None:
            return
        await self._bus.publish(
            Event(
                EventType.RISK_REJECTED,
                payload={
                    "symbol": signal.symbol,
                    "event_type": check.event_type.value,
                    "reason": check.reason,
                    **check.detail,
                    "ts": utcnow().isoformat(),
                },
                source="risk_engine",
            )
        )

    @property
    def win_stats(self) -> tuple[float, float]:
        """Current (win_rate, win_loss_ratio) used for Kelly sizing."""
        return self._win_rate, self._win_loss_ratio


__all__ = ["OrderProposal", "PortfolioView", "RiskEngine"]
