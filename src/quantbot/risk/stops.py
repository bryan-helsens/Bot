"""Stop-loss, trailing-stop, take-profit and break-even calculations.

Pure functions and a small :class:`StopManager` that, given a position and the
current price, computes the protective levels and decides whether any of them is
hit. All logic is side-aware (long vs short) and expressed in :class:`Decimal`.

These helpers are used both live (by the execution layer to place/move protective
orders) and in the backtester (to simulate exits), guaranteeing identical
behaviour between simulation and production.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantbot.core.config import RiskSettings
from quantbot.core.constants import ExitReason, PositionSide
from quantbot.core.models import Position, TakeProfitLevel


def stop_loss_price(side: PositionSide, entry: Decimal, stop_pct: Decimal) -> Decimal:
    """Absolute stop-loss price for a position at *stop_pct* from *entry*."""
    if side is PositionSide.LONG:
        return entry * (Decimal(1) - stop_pct)
    return entry * (Decimal(1) + stop_pct)


def take_profit_price(side: PositionSide, entry: Decimal, tp_pct: Decimal) -> Decimal:
    """Absolute take-profit price for a position at *tp_pct* from *entry*."""
    if side is PositionSide.LONG:
        return entry * (Decimal(1) + tp_pct)
    return entry * (Decimal(1) - tp_pct)


def build_take_profit_ladder(
    side: PositionSide, entry: Decimal, levels: list[tuple[Decimal, Decimal]]
) -> list[TakeProfitLevel]:
    """Build a take-profit ladder from ``(price_fraction, size_fraction)`` tuples."""
    ladder: list[TakeProfitLevel] = []
    for price_frac, size_frac in levels:
        ladder.append(
            TakeProfitLevel(
                price=take_profit_price(side, entry, price_frac),
                size_fraction=size_frac,
            )
        )
    return ladder


def trailing_stop_price(
    side: PositionSide, extreme_price: Decimal, trail_pct: Decimal
) -> Decimal:
    """Trailing-stop price given the best price seen (*extreme_price*).

    For a long, the extreme is the highest price since entry; the stop trails
    ``trail_pct`` below it. For a short it trails above the lowest price.
    """
    if side is PositionSide.LONG:
        return extreme_price * (Decimal(1) - trail_pct)
    return extreme_price * (Decimal(1) + trail_pct)


def is_stop_hit(side: PositionSide, stop: Decimal, price: Decimal) -> bool:
    """Whether *price* has reached/breached the stop for *side*."""
    if side is PositionSide.LONG:
        return price <= stop
    return price >= stop


def is_take_profit_hit(side: PositionSide, tp: Decimal, price: Decimal) -> bool:
    """Whether *price* has reached the take-profit for *side*."""
    if side is PositionSide.LONG:
        return price >= tp
    return price <= tp


@dataclass(slots=True)
class StopDecision:
    """Outcome of evaluating a position's protective levels for one price tick."""

    should_exit: bool
    exit_reason: ExitReason | None = None
    exit_fraction: Decimal = Decimal("1")
    new_stop_loss: Decimal | None = None
    new_trailing_stop: Decimal | None = None
    break_even_armed: bool = False
    triggered_tp_index: int | None = None


class StopManager:
    """Compute and update protective levels for an open position."""

    def __init__(self, settings: RiskSettings) -> None:
        self._cfg = settings

    def initial_levels(
        self,
        side: PositionSide,
        entry: Decimal,
        *,
        stop_pct: Decimal | None = None,
    ) -> tuple[Decimal, list[TakeProfitLevel]]:
        """Return the initial ``(stop_loss, take_profit_ladder)`` for a new position."""
        sl_pct = stop_pct if stop_pct is not None else self._cfg.default_stop_loss_pct
        stop = stop_loss_price(side, entry, sl_pct)
        ladder = build_take_profit_ladder(side, entry, self._cfg.take_profit_levels)
        return stop, ladder

    def evaluate(self, position: Position, price: Decimal) -> StopDecision:
        """Evaluate *position* against the current *price*.

        Checks, in priority order: hard stop-loss, trailing stop, take-profit
        ladder rungs, and break-even arming. Returns a :class:`StopDecision`
        describing any exit and any protective-level updates to persist.
        """
        side = position.side
        entry = position.entry_price

        # 1. Hard stop-loss.
        if position.stop_loss is not None and is_stop_hit(side, position.stop_loss, price):
            return StopDecision(True, ExitReason.STOP_LOSS, Decimal("1"))

        # 2. Trailing stop.
        if position.trailing_stop_price is not None and is_stop_hit(
            side, position.trailing_stop_price, price
        ):
            return StopDecision(True, ExitReason.TRAILING_STOP, Decimal("1"))

        decision = StopDecision(False)

        # 3. Take-profit ladder — exit the configured fraction at the first
        #    untriggered rung that price has reached.
        for index, level in enumerate(position.take_profit_levels):
            if not level.triggered and is_take_profit_hit(side, level.price, price):
                decision.should_exit = True
                decision.exit_reason = ExitReason.TAKE_PROFIT
                decision.exit_fraction = level.size_fraction
                decision.triggered_tp_index = index
                break

        # 4. Trailing-stop update (move it up/down as price extends in our favour).
        trail_pct = self._cfg.trailing_stop_pct
        if trail_pct > 0:
            new_trail = self._update_trailing(position, price, trail_pct)
            if new_trail is not None:
                decision.new_trailing_stop = new_trail

        # 5. Break-even: once profit exceeds the trigger, move stop to entry.
        be_trigger = self._cfg.break_even_trigger_pct
        if be_trigger > 0 and not position.break_even_armed:
            if self._profit_pct(side, entry, price) >= be_trigger:
                decision.break_even_armed = True
                decision.new_stop_loss = entry

        return decision

    # ------------------------------------------------------------------ helpers

    def _update_trailing(
        self, position: Position, price: Decimal, trail_pct: Decimal
    ) -> Decimal | None:
        """Compute a tightened trailing stop, if price extended favourably."""
        side = position.side
        candidate = trailing_stop_price(side, price, trail_pct)
        current = position.trailing_stop_price
        if current is None:
            # Only arm the trailing stop once in profit to avoid immediate stop-out.
            if self._profit_pct(side, position.entry_price, price) <= 0:
                return None
            return candidate
        # Move the stop only in the favourable direction (never loosen it).
        if side is PositionSide.LONG and candidate > current:
            return candidate
        if side is PositionSide.SHORT and candidate < current:
            return candidate
        return None

    @staticmethod
    def _profit_pct(side: PositionSide, entry: Decimal, price: Decimal) -> Decimal:
        if entry <= 0:
            return Decimal("0")
        raw = (price - entry) / entry
        return raw if side is PositionSide.LONG else -raw


__all__ = [
    "StopDecision",
    "StopManager",
    "build_take_profit_ladder",
    "is_stop_hit",
    "is_take_profit_hit",
    "stop_loss_price",
    "take_profit_price",
    "trailing_stop_price",
]
