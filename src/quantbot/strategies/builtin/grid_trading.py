"""Grid trading strategy.

Places a ladder of buy levels below and sell levels above a reference price and
trades the oscillation: a buy signal fires when price crosses *down* through an
untriggered buy level, a sell signal when price crosses *up* through a sell
level. The grid is bounded — a fixed number of levels and a hard floor/ceiling —
so it can **never** average down indefinitely, in line with QuantBot's risk
rules. Levels re-arm once price moves back past them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from quantbot.core.constants import Side, SignalType
from quantbot.core.models import Signal
from quantbot.strategies.base import BaseStrategy, StrategyContext
from quantbot.strategies.registry import register_strategy


@register_strategy
class GridTradingStrategy(BaseStrategy):
    """Bounded grid trading strategy (no unlimited averaging down)."""

    name: ClassVar[str] = "GridTradingStrategy"
    default_params: ClassVar[dict] = {
        "grid_levels": 5,       # levels per side
        "grid_spacing_pct": 0.01,  # spacing between levels (fraction)
        "recenter_pct": 0.10,   # recenter the grid if price drifts this far
    }
    min_candles: ClassVar[int] = 2

    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        levels = int(self.param("grid_levels"))
        spacing = Decimal(str(self.param("grid_spacing_pct")))
        center = self._state.get("center")
        price = ctx.price

        if center is None or self._needs_recenter(price, center):
            self._build_grid(price, levels, spacing)
            return None

        prev_price = Decimal(str(ctx.closes[-2]))
        # Buy when price crosses down through the nearest untriggered buy level.
        for level in self._state["buy_levels"]:
            if not level["armed"]:
                continue
            lp = level["price"]
            if prev_price > lp >= price:
                level["armed"] = False
                self._rearm_opposite("sell_levels", lp)
                return self.make_signal(
                    ctx, Side.BUY, signal_type=SignalType.ENTRY, strength=0.6,
                    reason="grid_buy_level", level=float(lp),
                )
        # Sell when price crosses up through the nearest untriggered sell level.
        for level in self._state["sell_levels"]:
            if not level["armed"]:
                continue
            lp = level["price"]
            if prev_price < lp <= price:
                level["armed"] = False
                self._rearm_opposite("buy_levels", lp)
                return self.make_signal(
                    ctx, Side.SELL, signal_type=SignalType.ENTRY, strength=0.6,
                    reason="grid_sell_level", level=float(lp),
                )
        return None

    def _build_grid(self, center: Decimal, levels: int, spacing: Decimal) -> None:
        """(Re)construct the grid centred on *center*."""
        self._state["center"] = center
        self._state["buy_levels"] = [
            {"price": center * (Decimal(1) - spacing * i), "armed": True}
            for i in range(1, levels + 1)
        ]
        self._state["sell_levels"] = [
            {"price": center * (Decimal(1) + spacing * i), "armed": True}
            for i in range(1, levels + 1)
        ]
        self.log.debug("grid_built", center=float(center), levels=levels)

    def _needs_recenter(self, price: Decimal, center: Decimal) -> bool:
        drift = abs(price - center) / center if center else Decimal(0)
        return drift > Decimal(str(self.param("recenter_pct")))

    def _rearm_opposite(self, side_key: str, crossed_price: Decimal) -> None:
        """Re-arm opposite-side levels so the grid keeps oscillating."""
        for level in self._state.get(side_key, []):
            if side_key == "sell_levels" and level["price"] > crossed_price:
                level["armed"] = True
            elif side_key == "buy_levels" and level["price"] < crossed_price:
                level["armed"] = True


__all__ = ["GridTradingStrategy"]
