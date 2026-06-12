"""The strategy base class and the per-evaluation context.

Design goals:
    * **Stateless-by-default** — strategies read from the :class:`StrategyContext`
      (market data + indicators) and return a signal; any internal state they
      keep (e.g. grid levels) is explicit and serialisable.
    * **Pure decision-making** — a strategy never touches the exchange, the risk
      engine or persistence. It only *suggests* via a
      :class:`~quantbot.core.models.Signal`. This keeps strategies trivial to
      unit-test and backtest, and guarantees the risk engine is never bypassed.
    * **Parameter validation** — declared defaults are validated and merged with
      user-supplied params at construction.

Subclasses implement :meth:`on_candle`. Optional hooks (:meth:`on_init`,
:meth:`on_trade_closed`) have safe no-op defaults.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

from quantbot.core.constants import SignalType, Timeframe
from quantbot.core.exceptions import StrategyConfigError
from quantbot.core.logging import get_logger
from quantbot.core.models import Candle, Signal, Trade

FloatArray = npt.NDArray[np.float64]


@dataclass(slots=True)
class StrategyContext:
    """Everything a strategy needs to evaluate one closed candle.

    The context exposes recent OHLCV as numpy arrays (oldest→newest) so indicator
    functions can be applied directly, plus the latest :class:`Candle` and a
    free-form ``extra`` mapping for cross-timeframe or regime data the engine
    chooses to inject.
    """

    symbol: str
    timeframe: Timeframe
    candle: Candle
    opens: FloatArray
    highs: FloatArray
    lows: FloatArray
    closes: FloatArray
    volumes: FloatArray
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def price(self) -> Decimal:
        """Latest close price as a Decimal (entry reference)."""
        return self.candle.close

    @property
    def length(self) -> int:
        """Number of candles available in the context."""
        return int(self.closes.size)

    def has(self, minimum: int) -> bool:
        """Whether at least *minimum* candles are available."""
        return self.length >= minimum


class BaseStrategy(abc.ABC):
    """Abstract base for all trading strategies.

    Class attributes:
        name: Human-readable strategy name (defaults to the class name).
        default_params: Declared parameters with their default values. User
            params are validated against these keys at construction.
        min_candles: Minimum candles required before the strategy will signal.
    """

    name: ClassVar[str] = "BaseStrategy"
    default_params: ClassVar[dict[str, Any]] = {}
    min_candles: ClassVar[int] = 1

    def __init__(
        self,
        *,
        symbols: list[str] | None = None,
        timeframes: list[Timeframe] | None = None,
        params: dict[str, Any] | None = None,
        instance_name: str | None = None,
    ) -> None:
        self.instance_name = instance_name or self.name
        self.symbols = symbols or []
        self.timeframes = timeframes or []
        self.params = self._merge_params(params or {})
        self._log = get_logger(type(self).__name__, strategy=self.instance_name)
        self._state: dict[str, Any] = {}

    # ------------------------------------------------------------------ params

    def _merge_params(self, user_params: dict[str, Any]) -> dict[str, Any]:
        """Validate *user_params* against ``default_params`` and merge."""
        unknown = set(user_params) - set(self.default_params)
        if unknown and self.default_params:
            raise StrategyConfigError(
                f"Unknown parameters for {self.name}: {sorted(unknown)}",
                context={"unknown": sorted(unknown), "valid": sorted(self.default_params)},
            )
        merged = {**self.default_params, **user_params}
        return merged

    def param(self, key: str, default: Any = None) -> Any:
        """Read a parameter value."""
        return self.params.get(key, default)

    def update_params(self, new_params: dict[str, Any]) -> dict[str, Any]:
        """Live-update parameters, validated and coerced to each param's type.

        Unknown keys are rejected. Each value is coerced to the type of the matching
        ``default_params`` entry (so a string "40" from the dashboard becomes the
        right int/float). Returns the new full params dict. The change takes effect
        on the next candle — it does NOT touch persisted config files.
        """
        unknown = set(new_params) - set(self.default_params)
        if unknown and self.default_params:
            raise StrategyConfigError(
                f"Unknown parameters for {self.name}: {sorted(unknown)}",
                context={"unknown": sorted(unknown), "valid": sorted(self.default_params)},
            )
        for key, value in new_params.items():
            template = self.default_params.get(key)
            try:
                if isinstance(template, bool):
                    coerced: Any = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
                elif isinstance(template, int) and not isinstance(template, bool):
                    coerced = int(float(value))
                elif isinstance(template, float):
                    coerced = float(value)
                else:
                    coerced = value
            except (TypeError, ValueError) as exc:
                raise StrategyConfigError(
                    f"Invalid value for {key!r}: {value!r}", context={"param": key}
                ) from exc
            self.params[key] = coerced
        self._log.info("strategy_params_updated", **{k: self.params[k] for k in new_params})
        return self.params

    # ------------------------------------------------------------------ state

    @property
    def state(self) -> dict[str, Any]:
        """Mutable per-instance state (serialisable for persistence)."""
        return self._state

    def reset(self) -> None:
        """Clear internal state (between backtest runs)."""
        self._state.clear()

    @property
    def log(self) -> Any:
        """Bound logger for this strategy instance."""
        return self._log

    # ------------------------------------------------------------------ hooks

    async def on_init(self) -> None:
        """Optional async setup hook (load models, warm caches)."""

    @abc.abstractmethod
    async def on_candle(self, ctx: StrategyContext) -> Signal | None:
        """Evaluate a freshly-closed candle and optionally return a signal.

        Returning ``None`` (or a signal with :class:`SignalType.NONE`) means "no
        action". The returned signal is advisory and will be validated by the
        risk engine.
        """

    async def on_trade_closed(self, trade: Trade) -> None:
        """Optional hook invoked after a trade this strategy opened closes."""

    # ------------------------------------------------------------------ helpers

    def make_signal(
        self,
        ctx: StrategyContext,
        side: Any,
        *,
        signal_type: SignalType = SignalType.ENTRY,
        strength: float = 0.6,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        reason: str = "",
        **meta: Any,
    ) -> Signal:
        """Construct a :class:`Signal` from the current context (convenience)."""
        return Signal(
            strategy=self.instance_name,
            symbol=ctx.symbol,
            timeframe=ctx.timeframe,
            side=side,
            signal_type=signal_type,
            strength=max(0.0, min(1.0, strength)),
            price=ctx.price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=reason or self.instance_name,
            meta=meta,
        )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.instance_name!r} params={self.params}>"


__all__ = ["BaseStrategy", "StrategyContext"]
