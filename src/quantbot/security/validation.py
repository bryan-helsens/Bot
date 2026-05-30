"""Input validation and sanitisation.

Validates untrusted input (config values, API request bodies, externally-sourced
symbols) before it reaches the trading core, raising
:class:`~quantbot.core.exceptions.ValidationError` on bad data. Keeping this in
one place ensures consistent, strict checks at every boundary.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from quantbot.core.constants import Timeframe
from quantbot.core.exceptions import ValidationError

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}$")
_API_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{16,128}$")


def validate_symbol(symbol: str) -> str:
    """Validate and normalise a trading symbol (uppercase, alphanumeric)."""
    if not isinstance(symbol, str):
        raise ValidationError("Symbol must be a string", context={"symbol": repr(symbol)})
    normalised = symbol.strip().upper()
    if not _SYMBOL_RE.match(normalised):
        raise ValidationError(
            f"Invalid symbol {symbol!r}", context={"symbol": symbol}
        )
    return normalised


def validate_positive_decimal(value: object, *, name: str = "value") -> Decimal:
    """Validate that *value* is a strictly positive decimal."""
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{name} is not a number: {value!r}") from exc
    if dec <= 0:
        raise ValidationError(f"{name} must be positive, got {dec}")
    if not dec.is_finite():
        raise ValidationError(f"{name} must be finite")
    return dec


def validate_non_negative_decimal(value: object, *, name: str = "value") -> Decimal:
    """Validate that *value* is a non-negative, finite decimal."""
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{name} is not a number: {value!r}") from exc
    if dec < 0 or not dec.is_finite():
        raise ValidationError(f"{name} must be a non-negative finite number, got {dec}")
    return dec


def validate_fraction(value: object, *, name: str = "fraction") -> Decimal:
    """Validate that *value* is a fraction in ``(0, 1]``."""
    dec = validate_positive_decimal(value, name=name)
    if dec > 1:
        raise ValidationError(f"{name} must be <= 1, got {dec}")
    return dec


def validate_timeframe(value: str) -> Timeframe:
    """Validate and parse a timeframe string."""
    try:
        return Timeframe.from_string(value)
    except ValueError as exc:
        raise ValidationError(str(exc), context={"timeframe": value}) from exc


def validate_leverage(value: object, *, max_leverage: int = 125) -> int:
    """Validate an integer leverage within ``[1, max_leverage]``."""
    try:
        leverage = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Leverage is not an integer: {value!r}") from exc
    if not (1 <= leverage <= max_leverage):
        raise ValidationError(f"Leverage must be in [1, {max_leverage}], got {leverage}")
    return leverage


def validate_api_key(value: str, *, name: str = "api_key") -> str:
    """Validate the shape of an API key (does not check it works)."""
    if not isinstance(value, str) or not _API_KEY_RE.match(value):
        raise ValidationError(f"{name} has an invalid format")
    return value


def sanitize_text(value: str, *, max_length: int = 500) -> str:
    """Strip control characters and clamp length (for log/notification safety)."""
    if not isinstance(value, str):
        value = str(value)
    cleaned = "".join(ch for ch in value if ch.isprintable() or ch in "\n\t")
    return cleaned[:max_length]


def validate_quantity_against_symbol(quantity: Decimal, *, step_size: Decimal, min_qty: Decimal) -> Decimal:
    """Validate an order quantity against a symbol's lot-size filters."""
    quantity = validate_positive_decimal(quantity, name="quantity")
    if min_qty > 0 and quantity < min_qty:
        raise ValidationError(f"Quantity {quantity} below minimum {min_qty}")
    if step_size > 0:
        remainder = (quantity / step_size) % 1
        if remainder != 0:
            raise ValidationError(
                f"Quantity {quantity} is not a multiple of step size {step_size}"
            )
    return quantity


__all__ = [
    "sanitize_text",
    "validate_api_key",
    "validate_fraction",
    "validate_leverage",
    "validate_non_negative_decimal",
    "validate_positive_decimal",
    "validate_quantity_against_symbol",
    "validate_symbol",
    "validate_timeframe",
]
