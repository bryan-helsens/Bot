"""Notification framework: the Notifier interface and the routing dispatcher.

A :class:`Notification` is a structured, channel-agnostic message. Concrete
notifiers (Telegram/Discord/Email) implement :meth:`Notifier.send`. The
:class:`NotificationRouter` fans a notification out to all enabled notifiers that
meet the configured severity threshold, with de-duplication (so a flapping
condition doesn't spam) and per-notifier error isolation.

The router subscribes to the engine's :class:`EventBus` and maps trading/system
events to notifications, so the rest of the bot just publishes events.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field

from quantbot.core.constants import EventType, NotificationChannel, Severity
from quantbot.core.events import Event, EventBus
from quantbot.core.logging import LoggerMixin
from quantbot.core.models import utcnow


@dataclass(slots=True)
class Notification:
    """A channel-agnostic notification message."""

    event_type: str
    severity: Severity
    title: str
    message: str
    payload: dict[str, object] = field(default_factory=dict)

    def dedup_key(self) -> str:
        """A key identifying near-identical notifications for de-duplication."""
        return f"{self.event_type}:{self.title}"

    def as_text(self) -> str:
        """Plain-text rendering used by text-only channels."""
        lines = [f"{_emoji(self.severity)} *{self.title}*", self.message]
        for key, value in self.payload.items():
            lines.append(f"• {key}: {value}")
        return "\n".join(lines)


def _emoji(severity: Severity) -> str:
    return {
        Severity.INFO: "ℹ️", Severity.WARNING: "⚠️",
        Severity.ERROR: "❌", Severity.CRITICAL: "🚨",
    }.get(severity, "•")


class Notifier(LoggerMixin, abc.ABC):
    """Abstract notification channel."""

    channel: NotificationChannel

    @abc.abstractmethod
    async def send(self, notification: Notification) -> bool:
        """Deliver *notification*; return ``True`` on success."""

    async def close(self) -> None:
        """Release any resources (override if needed)."""


class NotificationRouter(LoggerMixin):
    """Fan notifications out to enabled notifiers above a severity threshold."""

    def __init__(
        self,
        notifiers: list[Notifier],
        *,
        min_severity: Severity = Severity.INFO,
        dedup_window: float = 60.0,
    ) -> None:
        self._notifiers = notifiers
        self._min_severity = min_severity
        self._dedup_window = dedup_window
        self._recent: dict[str, float] = {}

    async def notify(self, notification: Notification) -> int:
        """Send *notification* to all eligible channels; return success count."""
        if notification.severity < self._min_severity:
            return 0
        if self._is_duplicate(notification):
            return 0
        sent = 0
        for notifier in self._notifiers:
            try:
                if await notifier.send(notification):
                    sent += 1
            except Exception as exc:  # noqa: BLE001 - one channel must not break others
                self.log.warning(
                    "notifier_failed", channel=notifier.channel.value, error=str(exc)
                )
        return sent

    def _is_duplicate(self, notification: Notification) -> bool:
        key = notification.dedup_key()
        now = time.monotonic()
        last = self._recent.get(key)
        self._recent[key] = now
        # Opportunistically prune old entries.
        if len(self._recent) > 1000:
            self._recent = {k: t for k, t in self._recent.items() if now - t < self._dedup_window}
        return last is not None and (now - last) < self._dedup_window

    async def close(self) -> None:
        for notifier in self._notifiers:
            await notifier.close()

    # ------------------------------------------------------------------ events

    def subscribe(self, bus: EventBus) -> None:
        """Subscribe the router to trading/system events on *bus*."""
        for event_type in _EVENT_MAP:
            bus.subscribe(event_type, self._on_event)

    async def _on_event(self, event: Event) -> None:
        builder = _EVENT_MAP.get(event.type)
        if builder is None:
            return
        notification = builder(event)
        if notification is not None:
            await self.notify(notification)


# ---------------------------------------------------------------------------
# Event -> Notification mapping
# ---------------------------------------------------------------------------


def _trade_opened(event: Event) -> Notification:
    return Notification(
        event_type="trade_opened", severity=Severity.INFO, title="New Trade Opened",
        message=f"{event.get('side', '').upper()} {event.get('symbol')} @ {event.get('entry_price')}",
        payload={"stop_loss": event.get("stop_loss"), "quantity": event.get("quantity")},
    )


def _trade_closed(event: Event) -> Notification:
    pnl = event.get("net_pnl", "0")
    severity = Severity.INFO
    return Notification(
        event_type="trade_closed", severity=severity, title="Trade Closed",
        message=f"{event.get('symbol')} closed @ {event.get('exit_price')} ({event.get('reason')})",
        payload={"net_pnl": pnl},
    )


def _risk_rejected(event: Event) -> Notification:
    return Notification(
        event_type="risk_rejected", severity=Severity.WARNING, title="Order Rejected by Risk",
        message=f"{event.get('symbol')}: {event.get('reason')}",
        payload={"event_type": event.get("event_type")},
    )


def _connection_lost(event: Event) -> Notification:
    return Notification(
        event_type="connection_lost", severity=Severity.ERROR, title="Connection Lost",
        message=f"Lost connection to {event.get('url', 'exchange')}",
    )


def _connection_restored(event: Event) -> Notification:
    return Notification(
        event_type="connection_restored", severity=Severity.INFO, title="Connection Restored",
        message=f"Reconnected to {event.get('url', 'exchange')}",
    )


def _system_error(event: Event) -> Notification:
    return Notification(
        event_type="system_error", severity=Severity.CRITICAL, title="System Error",
        message=str(event.get("error", "Unknown error")),
    )


_EVENT_MAP = {
    EventType.TRADE_OPENED: _trade_opened,
    EventType.TRADE_CLOSED: _trade_closed,
    EventType.RISK_REJECTED: _risk_rejected,
    EventType.CONNECTION_LOST: _connection_lost,
    EventType.CONNECTION_RESTORED: _connection_restored,
    EventType.SYSTEM_ERROR: _system_error,
}


__all__ = ["Notification", "NotificationRouter", "Notifier"]
