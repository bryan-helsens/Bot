"""Structured logging configuration for QuantBot.

Wraps `structlog` on top of the stdlib :mod:`logging` so that:

* In production (``LOG_FORMAT=json``) every line is a single JSON object, ideal
  for log shippers (Loki/ELK/CloudWatch).
* In development (``LOG_FORMAT=console``) output is colourised and human-readable.
* Secrets (api keys, tokens, passwords) are **redacted** by a processor before
  anything is rendered, so credentials never leak into logs.
* Every log entry carries an ISO-8601 UTC timestamp, level and logger name, and
  any bound context (e.g. ``symbol``, ``strategy``, ``order_id``).

Call :func:`configure_logging` once at startup, then obtain loggers via
:func:`get_logger`.
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from collections.abc import Callable
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from quantbot.core.constants import LogFormat

# ---------------------------------------------------------------------------
# In-memory log ring buffer (for the dashboard log panel)
# ---------------------------------------------------------------------------


class LogBuffer:
    """Keeps the most recent log entries in memory for the API/dashboard.

    A structlog processor (:func:`_capture_to_buffer`) appends a lightweight copy
    of every rendered event here, so the dashboard can show "what the bot is doing"
    live without reading files. Bounded, so it never grows without limit.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self._buf: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def add(self, entry: dict[str, Any]) -> None:
        self._buf.append(entry)

    def recent(self, limit: int = 200, *, level: str | None = None) -> list[dict[str, Any]]:
        items = list(self._buf)
        if level:
            wanted = level.upper()
            items = [e for e in items if str(e.get("level", "")).upper() == wanted]
        return items[-limit:]

    def clear(self) -> None:
        self._buf.clear()


#: Process-wide buffer the dashboard reads via ``GET /system/logs``.
LOG_BUFFER = LogBuffer()


def _capture_to_buffer(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """structlog processor: snapshot each event into :data:`LOG_BUFFER`."""
    reserved = {"event", "level", "timestamp", "logger", "stack", "exception"}
    LOG_BUFFER.add(
        {
            "ts": event_dict.get("timestamp"),
            "level": str(event_dict.get("level", "info")),
            "event": str(event_dict.get("event", "")),
            "logger": event_dict.get("logger", ""),
            "data": {k: str(v) for k, v in event_dict.items() if k not in reserved},
        }
    )
    return event_dict

# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

#: Substrings (case-insensitive) whose values are masked in log output.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "api_secret",
        "apikey",
        "secret",
        "password",
        "passwd",
        "token",
        "jwt",
        "authorization",
        "signature",
        "private_key",
        "encryption_key",
        "webhook_url",
    }
)

_REDACTED = "***REDACTED***"


def _is_sensitive(key: str) -> bool:
    """Whether *key* names a sensitive value that must be redacted."""
    lowered = key.lower()
    return any(token in lowered for token in _SENSITIVE_KEYS)


def redact_secrets(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """structlog processor that masks sensitive values in the event dict."""
    for key in list(event_dict.keys()):
        if _is_sensitive(key):
            event_dict[key] = _REDACTED
    return event_dict


def _add_logger_name(logger: logging.Logger, _method: str, event_dict: EventDict) -> EventDict:
    """Ensure the logger name is present under the ``logger`` key."""
    record = event_dict.get("logger")
    if not record:
        event_dict["logger"] = getattr(logger, "name", "quantbot")
    return event_dict


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_configured: bool = False


def configure_logging(
    *,
    level: str = "INFO",
    fmt: LogFormat = LogFormat.CONSOLE,
    utc: bool = True,
) -> None:
    """Configure stdlib logging + structlog for the whole process.

    Args:
        level: Minimum log level name (e.g. ``"INFO"``, ``"DEBUG"``).
        fmt: Output format — JSON for production, console for development.
        utc: Whether timestamps are rendered in UTC (recommended).

    This function is idempotent; calling it again reconfigures the renderers.
    """
    global _configured

    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):  # pragma: no cover - defensive
        numeric_level = logging.INFO

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=utc)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        _add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        redact_secrets,
        _capture_to_buffer,
    ]

    renderer: Processor
    if fmt is LogFormat.JSON:
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (used by third-party libs) through the same level.
    logging.basicConfig(
        format="%(message)s",
        level=numeric_level,
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True,
    )
    # Tame noisy third-party loggers.
    for noisy in ("websockets", "asyncio", "aiohttp.access", "urllib3"):
        logging.getLogger(noisy).setLevel(max(numeric_level, logging.WARNING))

    _configured = True


def configure_from_settings(settings: Any | None = None) -> None:
    """Configure logging from a :class:`~quantbot.core.config.Settings` instance."""
    if settings is None:
        from quantbot.core.config import get_settings

        settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)


def get_logger(name: str | None = None, **initial_context: Any) -> structlog.stdlib.BoundLogger:
    """Return a bound structured logger.

    Args:
        name: Logger name (typically ``__name__``).
        **initial_context: Key/value pairs bound to every record from this logger.

    Lazily configures logging with defaults if :func:`configure_logging` has not
    been called yet, so importing modules never crash on logging.
    """
    if not _configured:
        configure_logging()
    logger = structlog.get_logger(name)
    if initial_context:
        logger = logger.bind(**initial_context)
    return logger  # type: ignore[no-any-return]


def bind_context(**kwargs: Any) -> None:
    """Bind key/values to the current async context (propagates to all logs)."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all context-local log bindings."""
    structlog.contextvars.clear_contextvars()


class LoggerMixin:
    """Mixin giving any class a lazily-created, class-named bound logger."""

    _logger: structlog.stdlib.BoundLogger | None = None

    @property
    def log(self) -> structlog.stdlib.BoundLogger:
        """A logger named after the concrete class."""
        if self._logger is None:
            self._logger = get_logger(type(self).__name__)
        return self._logger


__all__ = [
    "LoggerMixin",
    "bind_context",
    "clear_context",
    "configure_from_settings",
    "configure_logging",
    "get_logger",
    "redact_secrets",
]


# Re-export for callers that want the processor type without importing structlog.
_ProcessorType = Callable[[Any, str, EventDict], EventDict]
