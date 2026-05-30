"""Exception hierarchy for QuantBot.

A single rooted hierarchy (:class:`QuantBotError`) lets callers catch broad or
narrow categories deliberately. Every exception carries an optional structured
``context`` mapping so handlers and the audit log can record machine-readable
detail without string-parsing messages.

Design rules:
    * Infrastructure/transient failures (network, rate limit) derive from
      :class:`TransientError` and expose :attr:`retryable` so retry decorators
      can decide automatically.
    * Domain/logic failures derive from :class:`QuantBotError` directly and are
      *not* retryable.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class QuantBotError(Exception):
    """Base class for every error raised by QuantBot.

    Args:
        message: Human-readable description.
        context: Optional structured detail attached to the error.
    """

    #: Whether retrying the failed operation could plausibly succeed.
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context or {}

    def __str__(self) -> str:
        if self.context:
            ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{self.message} ({ctx})"
        return self.message

    def to_dict(self) -> dict[str, Any]:
        """Serialise the error for logging/audit purposes."""
        return {
            "error": type(self).__name__,
            "message": self.message,
            "retryable": self.retryable,
            "context": self.context,
        }


# ---------------------------------------------------------------------------
# Configuration & startup
# ---------------------------------------------------------------------------


class ConfigurationError(QuantBotError):
    """Invalid, missing or inconsistent configuration."""


class DependencyError(QuantBotError):
    """A required optional dependency or external service is unavailable."""


# ---------------------------------------------------------------------------
# Transient / infrastructure (retryable)
# ---------------------------------------------------------------------------


class TransientError(QuantBotError):
    """Base for transient failures that may succeed on retry."""

    retryable = True


class ConnectionLostError(TransientError):
    """A network or websocket connection dropped."""


class TimeoutError_(TransientError):
    """An operation exceeded its allotted time.

    Named with a trailing underscore to avoid shadowing the builtin
    :class:`TimeoutError`; exported as :data:`OperationTimeoutError`.
    """


#: Public alias avoiding the builtin name clash.
OperationTimeoutError = TimeoutError_


# ---------------------------------------------------------------------------
# Exchange
# ---------------------------------------------------------------------------


class ExchangeError(QuantBotError):
    """Base class for all exchange-related errors."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        ctx = dict(context or {})
        if code is not None:
            ctx.setdefault("code", code)
        super().__init__(message, context=ctx)
        self.code = code


class ExchangeConnectionError(ExchangeError, TransientError):
    """Failed to reach the exchange (DNS/TCP/TLS/5xx)."""

    retryable = True


class RateLimitError(ExchangeError, TransientError):
    """The exchange rate limit (HTTP 429 / weight) was hit.

    Args:
        retry_after: Suggested seconds to wait before retrying, if provided
            by the exchange.
    """

    retryable = True

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after: float | None = None,
        code: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        ctx = dict(context or {})
        if retry_after is not None:
            ctx.setdefault("retry_after", retry_after)
        super().__init__(message, code=code, context=ctx)
        self.retry_after = retry_after


class AuthenticationError(ExchangeError):
    """API key/secret rejected or signature invalid (not retryable)."""


class InsufficientBalanceError(ExchangeError):
    """Account balance is insufficient for the requested order."""


class InvalidOrderError(ExchangeError):
    """The exchange rejected the order parameters (filters, precision, notional)."""


class OrderNotFoundError(ExchangeError):
    """A referenced order does not exist on the exchange."""


class SymbolNotFoundError(ExchangeError):
    """A referenced trading symbol is unknown to the exchange."""


class MarketClosedError(ExchangeError):
    """The market/symbol is not currently tradable."""


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class StrategyError(QuantBotError):
    """Base class for strategy-related errors."""


class StrategyNotFoundError(StrategyError):
    """A requested strategy class is not registered."""


class StrategyConfigError(StrategyError):
    """A strategy received invalid parameters."""


class StrategyExecutionError(StrategyError):
    """A strategy raised while processing market data."""


# ---------------------------------------------------------------------------
# Risk (intentional, non-retryable control-flow signals)
# ---------------------------------------------------------------------------


class RiskError(QuantBotError):
    """Base class for risk-management rejections."""


class RiskRejectedError(RiskError):
    """The risk engine refused to approve an order.

    Args:
        reason: Short machine-readable rejection reason
            (see :class:`~quantbot.core.constants.RiskEventType`).
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        ctx = dict(context or {})
        if reason is not None:
            ctx.setdefault("reason", reason)
        super().__init__(message, context=ctx)
        self.reason = reason


class CircuitBreakerOpenError(RiskError):
    """Trading is paused because the circuit breaker is open."""


class EmergencyShutdownError(RiskError):
    """A global emergency shutdown has been triggered."""


# ---------------------------------------------------------------------------
# Execution & data
# ---------------------------------------------------------------------------


class ExecutionError(QuantBotError):
    """Order execution failed after risk approval."""


class OrderSyncError(QuantBotError):
    """Local order/position state could not be reconciled with the exchange."""


class DataError(QuantBotError):
    """Base class for market-data problems."""


class InsufficientDataError(DataError):
    """Not enough candles/history to compute the requested value."""


class DataIntegrityError(DataError):
    """Received data failed validation (gaps, duplicates, malformed)."""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class StorageError(QuantBotError):
    """Base class for database/cache errors."""


class DatabaseError(StorageError):
    """A database operation failed."""


class CacheError(StorageError):
    """A cache (Redis) operation failed."""


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class SecurityError(QuantBotError):
    """Base class for security-related errors."""


class EncryptionError(SecurityError):
    """Failed to encrypt/decrypt a secret."""


class ValidationError(SecurityError):
    """Untrusted input failed validation."""


# ---------------------------------------------------------------------------
# Backtest / optimisation
# ---------------------------------------------------------------------------


class BacktestError(QuantBotError):
    """Base class for backtesting errors."""


class OptimizationError(QuantBotError):
    """Parameter optimisation failed."""


__all__ = [
    "AuthenticationError",
    "BacktestError",
    "CacheError",
    "CircuitBreakerOpenError",
    "ConfigurationError",
    "ConnectionLostError",
    "DataError",
    "DataIntegrityError",
    "DatabaseError",
    "DependencyError",
    "EmergencyShutdownError",
    "EncryptionError",
    "ExchangeConnectionError",
    "ExchangeError",
    "ExecutionError",
    "InsufficientBalanceError",
    "InsufficientDataError",
    "InvalidOrderError",
    "MarketClosedError",
    "OperationTimeoutError",
    "OptimizationError",
    "OrderNotFoundError",
    "OrderSyncError",
    "QuantBotError",
    "RateLimitError",
    "RiskError",
    "RiskRejectedError",
    "SecurityError",
    "StorageError",
    "StrategyConfigError",
    "StrategyError",
    "StrategyExecutionError",
    "StrategyNotFoundError",
    "SymbolNotFoundError",
    "TimeoutError_",
    "TransientError",
    "ValidationError",
]
