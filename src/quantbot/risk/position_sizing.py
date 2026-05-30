"""Position sizing methods.

Given account equity, an entry price and a stop-loss (or volatility estimate),
each sizer returns a position *quantity*. All methods are capital-preserving by
construction: they cap the loss-if-stopped at a fixed fraction of equity and
never increase size to recover prior losses (no martingale).

Methods (see :class:`~quantbot.core.constants.SizingMethod`):
    * ``FIXED``      — a fixed fraction of equity as notional.
    * ``RISK``       — size so the stop-loss equals ``risk_per_trade`` of equity.
    * ``KELLY``      — capped Kelly fraction from historical win/loss stats.
    * ``VOLATILITY`` — ATR-based sizing for a constant risk unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantbot.core.config import RiskSettings
from quantbot.core.constants import SizingMethod
from quantbot.core.logging import get_logger
from quantbot.core.utils import safe_div, to_decimal

_log = get_logger(__name__)


@dataclass(slots=True)
class SizingInput:
    """Inputs required to size a position."""

    equity: Decimal
    price: Decimal
    stop_loss: Decimal | None = None
    atr: Decimal | None = None
    #: Historical stats for Kelly (win rate and avg win/loss ratio).
    win_rate: float | None = None
    win_loss_ratio: float | None = None
    #: Optional explicit risk fraction override (defaults to settings).
    risk_fraction: Decimal | None = None


@dataclass(slots=True)
class SizingResult:
    """Output of a sizing computation."""

    quantity: Decimal
    notional: Decimal
    risk_amount: Decimal
    method: SizingMethod
    reason: str = ""


class PositionSizer:
    """Compute position sizes according to the configured method."""

    def __init__(self, settings: RiskSettings) -> None:
        self._cfg = settings

    def size(self, data: SizingInput, *, method: SizingMethod | None = None) -> SizingResult:
        """Compute a position size for *data* using *method* (or the configured)."""
        method = method or self._cfg.sizing_method
        if data.equity <= 0 or data.price <= 0:
            return SizingResult(Decimal("0"), Decimal("0"), Decimal("0"), method, "non_positive_equity")

        if method is SizingMethod.FIXED:
            result = self._fixed(data)
        elif method is SizingMethod.RISK:
            result = self._risk(data)
        elif method is SizingMethod.KELLY:
            result = self._kelly(data)
        elif method is SizingMethod.VOLATILITY:
            result = self._volatility(data)
        else:  # pragma: no cover - guarded by enum
            result = self._risk(data)

        # Final safety clamp: never exceed the per-coin exposure cap as notional.
        max_notional = data.equity * self._cfg.max_exposure_per_coin
        if result.notional > max_notional and result.notional > 0:
            scale = max_notional / result.notional
            result = SizingResult(
                quantity=result.quantity * scale,
                notional=max_notional,
                risk_amount=result.risk_amount * scale,
                method=method,
                reason=result.reason + "+exposure_capped",
            )
        return result

    # ------------------------------------------------------------------ methods

    def _fixed(self, data: SizingInput) -> SizingResult:
        """A fixed fraction of equity deployed as notional."""
        fraction = data.risk_fraction if data.risk_fraction is not None else self._cfg.risk_per_trade
        notional = data.equity * fraction * Decimal("10")  # leverage-1 notional sizing
        notional = min(notional, data.equity * self._cfg.max_exposure_per_coin)
        qty = safe_div(notional, data.price)
        risk = self._risk_if_stopped(qty, data)
        return SizingResult(qty, qty * data.price, risk, SizingMethod.FIXED, "fixed_fraction")

    def _risk(self, data: SizingInput) -> SizingResult:
        """Size so that hitting the stop loses exactly ``risk_per_trade`` equity."""
        if data.stop_loss is None or data.stop_loss <= 0:
            # Fall back to the configured default stop distance.
            stop_distance = data.price * self._cfg.default_stop_loss_pct
        else:
            stop_distance = abs(data.price - data.stop_loss)
        if stop_distance <= 0:
            return SizingResult(Decimal("0"), Decimal("0"), Decimal("0"), SizingMethod.RISK, "zero_stop_distance")

        fraction = data.risk_fraction if data.risk_fraction is not None else self._cfg.risk_per_trade
        risk_amount = data.equity * fraction
        qty = safe_div(risk_amount, stop_distance)
        return SizingResult(qty, qty * data.price, risk_amount, SizingMethod.RISK, "fixed_risk")

    def _kelly(self, data: SizingInput) -> SizingResult:
        """Capped Kelly fraction from win rate and win/loss ratio."""
        win_rate = data.win_rate if data.win_rate is not None else 0.5
        ratio = data.win_loss_ratio if data.win_loss_ratio is not None else 1.0
        # Kelly fraction f* = W - (1-W)/R
        if ratio <= 0:
            kelly = 0.0
        else:
            kelly = win_rate - (1.0 - win_rate) / ratio
        kelly = max(0.0, kelly)
        capped = min(kelly, float(self._cfg.kelly_cap))
        fraction = to_decimal(capped)
        # Treat the Kelly fraction as the risk fraction in a risk-based sizing.
        kelly_input = SizingInput(
            equity=data.equity, price=data.price, stop_loss=data.stop_loss,
            risk_fraction=fraction,
        )
        result = self._risk(kelly_input)
        return SizingResult(
            result.quantity, result.notional, result.risk_amount,
            SizingMethod.KELLY, f"kelly_f={capped:.3f}",
        )

    def _volatility(self, data: SizingInput) -> SizingResult:
        """ATR-based sizing: risk a fixed fraction over an ATR-multiple stop."""
        if data.atr is None or data.atr <= 0:
            return self._risk(data)  # fall back if no volatility estimate
        # Use the ATR as the stop distance proxy.
        atr_input = SizingInput(
            equity=data.equity, price=data.price,
            stop_loss=data.price - data.atr, risk_fraction=data.risk_fraction,
        )
        result = self._risk(atr_input)
        return SizingResult(
            result.quantity, result.notional, result.risk_amount,
            SizingMethod.VOLATILITY, "atr_volatility",
        )

    # ------------------------------------------------------------------ helpers

    def _risk_if_stopped(self, qty: Decimal, data: SizingInput) -> Decimal:
        if data.stop_loss is not None and data.stop_loss > 0:
            return qty * abs(data.price - data.stop_loss)
        return qty * data.price * self._cfg.default_stop_loss_pct


__all__ = ["PositionSizer", "SizingInput", "SizingResult"]
