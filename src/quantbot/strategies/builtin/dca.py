"""Dollar-Cost-Averaging (DCA) strategy.

Accumulates a position in fixed steps, either on a time schedule (every N
candles) or on dips of a configured depth. Crucially this is **not** a martingale
or unlimited averaging-down system: the number of DCA entries is hard-capped by
``max_entries`` (and further bounded by the risk engine's
``max_averaging_entries``), and step sizes are constant — never increased to
"recover" losses. Once the cap is reached, no further entries are emitted.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class DCAStrategy(BaseStrategy):
    """Bounded dollar-cost-averaging accumulation strategy."""

    name: ClassVar[str] = "DCAStrategy"
    default_params: ClassVar[dict] = {
        "mode": "interval",        # "interval" | "dip"
        "interval_candles": 24,    # for interval mode
        "dip_pct": 0.03,           # for dip mode: buy after this drop from last entry
        "max_entries": 5,          # HARD cap on accumulation steps
        "side": "buy",             # accumulate long ("buy") — shorts not averaged
    }
    min_candles: ClassVar[int] = 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        entries = int(self._state.get("entries", 0))
        max_entries = int(self.param("max_entries"))
        # Hard stop: never average beyond the cap (anti-martingale rule).
        if entries >= max_entries:
            return None

        side = Side.BUY if str(self.param("side")).lower() == "buy" else Side.SELL
        mode = str(self.param("mode")).lower()
        price = ctx.price

        should_enter = False
        if mode == "interval":
            since = int(self._state.get("bars_since", 0)) + 1
            self._state["bars_since"] = since
            if entries == 0 or since >= int(self.param("interval_candles")):
                should_enter = True
                self._state["bars_since"] = 0
        elif mode == "dip":
            last = self._state.get("last_entry_price")
            if last is None:
                should_enter = True
            else:
                drop = (Decimal(str(last)) - price) / Decimal(str(last))
                if drop >= Decimal(str(self.param("dip_pct"))):
                    should_enter = True
        else:  # pragma: no cover - guarded by config in practice
            return None

        if not should_enter:
            return None

        self._state["entries"] = entries + 1
        self._state["last_entry_price"] = price
        # Strength decays with each successive entry so confluence weighting
        # naturally favours the initial entry over later averaging.
        strength = max(0.5, 0.7 - 0.05 * entries)
        return self.make_signal(
            ctx, side, signal_type=SignalType.ENTRY if entries == 0 else SignalType.INCREASE,
            strength=strength, reason=f"dca_entry_{entries + 1}",
            entry_number=entries + 1, max_entries=max_entries,
        )

    def reset(self) -> None:
        """Reset accumulation state (e.g. after the position fully closes)."""
        super().reset()


__all__ = ["DCAStrategy"]
