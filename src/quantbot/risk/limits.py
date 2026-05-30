"""Exposure, loss and drawdown limit checks.

:class:`LimitChecker` is a stateful guard tracking realised PnL over rolling
daily/weekly windows and the equity high-water mark for drawdown. It exposes a
set of individual checks returning a :class:`LimitCheck` (pass/fail + reason) plus
``check_new_position`` which runs all pre-trade limits at once.

It also enforces QuantBot's hard trading rules:
    * **No martingale** — sizes may never be increased to recover losses.
    * **No unlimited averaging down** — the number of averaging entries per
      position is capped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from quantbot.core.config import RiskSettings
from quantbot.core.constants import RiskEventType
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import Position


@dataclass(slots=True)
class LimitCheck:
    """Result of a single limit check."""

    passed: bool
    event_type: RiskEventType | None = None
    reason: str = ""
    detail: dict[str, object] = field(default_factory=dict)

    @classmethod
    def ok(cls) -> LimitCheck:
        """A passing check."""
        return cls(True)

    @classmethod
    def fail(cls, event: RiskEventType, reason: str, **detail: object) -> LimitCheck:
        """A failing check carrying an event type and reason."""
        return cls(False, event, reason, detail)


@dataclass(slots=True)
class PnLWindow:
    """Tracks realised PnL within a rolling time window."""

    duration: timedelta
    entries: list[tuple[datetime, Decimal]] = field(default_factory=list)

    def add(self, pnl: Decimal, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        self.entries.append((now, pnl))
        self._prune(now)

    def total(self, *, now: datetime | None = None) -> Decimal:
        now = now or datetime.now(UTC)
        self._prune(now)
        return sum((pnl for _, pnl in self.entries), Decimal("0"))

    def _prune(self, now: datetime) -> None:
        cutoff = now - self.duration
        self.entries = [(ts, pnl) for ts, pnl in self.entries if ts >= cutoff]


class LimitChecker(LoggerMixin):
    """Stateful pre- and post-trade limit enforcement."""

    def __init__(self, settings: RiskSettings) -> None:
        self._cfg = settings
        self._daily = PnLWindow(timedelta(days=1))
        self._weekly = PnLWindow(timedelta(days=7))
        self._equity_peak: Decimal = Decimal("0")
        self._start_equity: Decimal = Decimal("0")

    # ------------------------------------------------------------------ state

    def set_starting_equity(self, equity: Decimal) -> None:
        """Initialise the equity baseline and high-water mark."""
        self._start_equity = equity
        self._equity_peak = max(self._equity_peak, equity)

    def record_trade_pnl(self, pnl: Decimal, *, now: datetime | None = None) -> None:
        """Record a realised trade PnL into the rolling windows."""
        self._daily.add(pnl, now=now)
        self._weekly.add(pnl, now=now)

    def update_equity(self, equity: Decimal) -> None:
        """Update the equity high-water mark for drawdown tracking."""
        if equity > self._equity_peak:
            self._equity_peak = equity

    # ------------------------------------------------------------------ metrics

    def current_drawdown(self, equity: Decimal) -> Decimal:
        """Current drawdown as a positive fraction from the high-water mark."""
        if self._equity_peak <= 0:
            return Decimal("0")
        dd = (self._equity_peak - equity) / self._equity_peak
        return max(Decimal("0"), dd)

    def daily_pnl(self, *, now: datetime | None = None) -> Decimal:
        return self._daily.total(now=now)

    def weekly_pnl(self, *, now: datetime | None = None) -> Decimal:
        return self._weekly.total(now=now)

    # ------------------------------------------------------------------ checks

    def check_max_open_trades(self, open_count: int) -> LimitCheck:
        if open_count >= self._cfg.max_open_trades:
            return LimitCheck.fail(
                RiskEventType.MAX_OPEN_TRADES,
                f"Max open trades reached ({open_count}/{self._cfg.max_open_trades})",
                open_count=open_count,
            )
        return LimitCheck.ok()

    def check_coin_exposure(
        self, symbol: str, new_notional: Decimal, existing_notional: Decimal, equity: Decimal
    ) -> LimitCheck:
        if equity <= 0:
            return LimitCheck.ok()
        total = (existing_notional + new_notional) / equity
        if total > self._cfg.max_exposure_per_coin:
            return LimitCheck.fail(
                RiskEventType.MAX_EXPOSURE,
                f"Coin exposure {total:.2%} exceeds cap {self._cfg.max_exposure_per_coin:.2%}",
                symbol=symbol, exposure=float(total),
            )
        return LimitCheck.ok()

    def check_portfolio_exposure(
        self, new_notional: Decimal, total_notional: Decimal, equity: Decimal
    ) -> LimitCheck:
        if equity <= 0:
            return LimitCheck.ok()
        total = (total_notional + new_notional) / equity
        if total > self._cfg.max_portfolio_exposure:
            return LimitCheck.fail(
                RiskEventType.MAX_EXPOSURE,
                f"Portfolio exposure {total:.2%} exceeds cap {self._cfg.max_portfolio_exposure:.2%}",
                exposure=float(total),
            )
        return LimitCheck.ok()

    def check_daily_loss(self, equity: Decimal, *, now: datetime | None = None) -> LimitCheck:
        base = self._start_equity or equity
        if base <= 0:
            return LimitCheck.ok()
        loss_fraction = -self._daily.total(now=now) / base
        if loss_fraction >= self._cfg.max_daily_loss:
            return LimitCheck.fail(
                RiskEventType.DAILY_LOSS_LIMIT,
                f"Daily loss {loss_fraction:.2%} hit limit {self._cfg.max_daily_loss:.2%}",
                loss=float(loss_fraction),
            )
        return LimitCheck.ok()

    def check_weekly_loss(self, equity: Decimal, *, now: datetime | None = None) -> LimitCheck:
        base = self._start_equity or equity
        if base <= 0:
            return LimitCheck.ok()
        loss_fraction = -self._weekly.total(now=now) / base
        if loss_fraction >= self._cfg.max_weekly_loss:
            return LimitCheck.fail(
                RiskEventType.WEEKLY_LOSS_LIMIT,
                f"Weekly loss {loss_fraction:.2%} hit limit {self._cfg.max_weekly_loss:.2%}",
                loss=float(loss_fraction),
            )
        return LimitCheck.ok()

    def check_drawdown(self, equity: Decimal) -> LimitCheck:
        dd = self.current_drawdown(equity)
        if dd >= self._cfg.max_drawdown:
            return LimitCheck.fail(
                RiskEventType.MAX_DRAWDOWN,
                f"Drawdown {dd:.2%} hit limit {self._cfg.max_drawdown:.2%}",
                drawdown=float(dd),
            )
        return LimitCheck.ok()

    def check_averaging(self, existing: Position | None, new_size: Decimal, last_size: Decimal) -> LimitCheck:
        """Enforce the no-martingale / bounded-averaging rules for add-ons."""
        if existing is None:
            return LimitCheck.ok()
        # No unlimited averaging down.
        if not self._cfg.allow_unlimited_averaging:
            if existing.averaging_entries >= self._cfg.max_averaging_entries:
                return LimitCheck.fail(
                    RiskEventType.AVERAGING_LIMIT,
                    f"Averaging cap reached ({existing.averaging_entries}/{self._cfg.max_averaging_entries})",
                    entries=existing.averaging_entries,
                )
        # No martingale: a follow-up entry may not be larger than the prior one.
        if not self._cfg.allow_martingale and last_size > 0 and new_size > last_size:
            return LimitCheck.fail(
                RiskEventType.MARTINGALE_BLOCKED,
                "Martingale blocked: averaging size exceeds previous entry",
                new_size=float(new_size), last_size=float(last_size),
            )
        return LimitCheck.ok()

    # ------------------------------------------------------------------ combined

    def check_new_position(
        self,
        *,
        symbol: str,
        new_notional: Decimal,
        existing_coin_notional: Decimal,
        total_portfolio_notional: Decimal,
        equity: Decimal,
        open_count: int,
        now: datetime | None = None,
    ) -> LimitCheck:
        """Run all pre-trade limit checks; return the first failure (or OK)."""
        for check in (
            self.check_max_open_trades(open_count),
            self.check_daily_loss(equity, now=now),
            self.check_weekly_loss(equity, now=now),
            self.check_drawdown(equity),
            self.check_coin_exposure(symbol, new_notional, existing_coin_notional, equity),
            self.check_portfolio_exposure(new_notional, total_portfolio_notional, equity),
        ):
            if not check.passed:
                self.log.warning("limit_breached", reason=check.reason, **check.detail)
                return check
        return LimitCheck.ok()


__all__ = ["LimitCheck", "LimitChecker", "PnLWindow"]
