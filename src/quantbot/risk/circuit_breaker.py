"""Circuit breaker and emergency shutdown.

Two complementary safety mechanisms:

* :class:`CircuitBreaker` — a self-resetting trip that *pauses new entries* after
  a run of consecutive losses (or a rapid loss burst), then cools down for a
  configured period before automatically re-enabling trading. This stops the bot
  from compounding losses during an adverse streak without human intervention.

* :class:`EmergencyShutdown` — a latched, manual-or-automatic kill switch that
  halts *all* trading and signals the engine to flatten positions. Unlike the
  circuit breaker it does **not** auto-reset; it requires an explicit ``reset()``
  (operator action) to resume.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal

from quantbot.core.config import RiskSettings
from quantbot.core.constants import RiskEventType
from quantbot.core.logging import LoggerMixin
from quantbot.risk.limits import LimitCheck


@dataclass(slots=True)
class CircuitState:
    """Observable circuit-breaker state (for dashboards/health)."""

    tripped: bool
    consecutive_losses: int
    cooldown_remaining: float
    trips_total: int


class CircuitBreaker(LoggerMixin):
    """Pause entries after consecutive losses; auto-reset after a cooldown."""

    def __init__(self, settings: RiskSettings, *, time_fn=time.monotonic) -> None:
        self._cfg = settings
        self._time = time_fn
        self._consecutive_losses = 0
        self._tripped_until = 0.0
        self._trips_total = 0

    # ------------------------------------------------------------------ feed

    def record_trade(self, pnl: Decimal) -> bool:
        """Record a closed trade's PnL; return ``True`` if this trips the breaker."""
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0  # a win resets the streak

        if (
            self._cfg.circuit_breaker_losses > 0
            and self._consecutive_losses >= self._cfg.circuit_breaker_losses
            and not self.is_tripped
        ):
            self._trip()
            return True
        return False

    def _trip(self) -> None:
        self._tripped_until = self._time() + self._cfg.circuit_breaker_cooldown
        self._trips_total += 1
        self.log.warning(
            "circuit_breaker_tripped",
            consecutive_losses=self._consecutive_losses,
            cooldown=self._cfg.circuit_breaker_cooldown,
        )

    # ------------------------------------------------------------------ query

    @property
    def is_tripped(self) -> bool:
        """Whether trading is currently paused by the breaker."""
        if self._tripped_until <= 0:
            return False
        if self._time() >= self._tripped_until:
            # Cooldown elapsed → auto-reset.
            self._tripped_until = 0.0
            self._consecutive_losses = 0
            self.log.info("circuit_breaker_reset")
            return False
        return True

    @property
    def cooldown_remaining(self) -> float:
        """Seconds remaining in the cooldown (0 if not tripped)."""
        return max(0.0, self._tripped_until - self._time())

    def check(self) -> LimitCheck:
        """Pre-trade gate: fail while the breaker is tripped."""
        if self.is_tripped:
            return LimitCheck.fail(
                RiskEventType.CIRCUIT_BREAKER,
                f"Circuit breaker active; cooldown {self.cooldown_remaining:.0f}s remaining",
                cooldown_remaining=round(self.cooldown_remaining, 1),
            )
        return LimitCheck.ok()

    def manual_trip(self) -> None:
        """Force-trip the breaker (operator action)."""
        self._consecutive_losses = max(self._consecutive_losses, self._cfg.circuit_breaker_losses)
        self._trip()

    def reset(self) -> None:
        """Manually clear the breaker."""
        self._tripped_until = 0.0
        self._consecutive_losses = 0

    def state(self) -> CircuitState:
        """Snapshot for monitoring."""
        return CircuitState(
            tripped=self.is_tripped,
            consecutive_losses=self._consecutive_losses,
            cooldown_remaining=round(self.cooldown_remaining, 1),
            trips_total=self._trips_total,
        )


@dataclass(slots=True)
class EmergencyShutdown(LoggerMixin):
    """Latched kill switch halting all trading until explicitly reset."""

    _active: bool = field(default=False)
    _reason: str = field(default="")
    _triggered_at: float = field(default=0.0)

    def trigger(self, reason: str) -> None:
        """Activate the emergency shutdown (idempotent; keeps the first reason)."""
        if self._active:
            return
        self._active = True
        self._reason = reason
        self._triggered_at = time.time()
        self.log.critical("emergency_shutdown_triggered", reason=reason)

    def reset(self) -> None:
        """Clear the shutdown (operator action required to resume trading)."""
        if self._active:
            self.log.warning("emergency_shutdown_reset", previous_reason=self._reason)
        self._active = False
        self._reason = ""
        self._triggered_at = 0.0

    @property
    def active(self) -> bool:
        """Whether the shutdown is currently latched."""
        return self._active

    @property
    def reason(self) -> str:
        """The reason the shutdown was triggered (empty if inactive)."""
        return self._reason

    def check(self) -> LimitCheck:
        """Pre-trade gate: fail while shutdown is active."""
        if self._active:
            return LimitCheck.fail(
                RiskEventType.EMERGENCY_SHUTDOWN,
                f"Emergency shutdown active: {self._reason}",
                shutdown_reason=self._reason,
            )
        return LimitCheck.ok()


__all__ = ["CircuitBreaker", "CircuitState", "EmergencyShutdown"]
