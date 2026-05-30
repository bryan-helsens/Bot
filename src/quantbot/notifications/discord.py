"""Discord notifier via an incoming webhook."""

from __future__ import annotations

import aiohttp

from quantbot.core.constants import NotificationChannel, Severity
from quantbot.notifications.base import Notification, Notifier

# Discord embed colours per severity (decimal RGB).
_COLOURS = {
    Severity.INFO: 0x3FB950,
    Severity.WARNING: 0xD29922,
    Severity.ERROR: 0xF85149,
    Severity.CRITICAL: 0xDA3633,
}


class DiscordNotifier(Notifier):
    """Send rich-embed notifications to a Discord channel via a webhook URL."""

    channel = NotificationChannel.DISCORD

    def __init__(
        self,
        webhook_url: str,
        *,
        username: str = "QuantBot",
        session: aiohttp.ClientSession | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._url = webhook_url
        self._username = username
        self._session = session
        self._owns_session = session is None
        self._timeout = timeout

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def send(self, notification: Notification) -> bool:
        session = await self._ensure_session()
        embed = {
            "title": notification.title,
            "description": notification.message,
            "color": _COLOURS.get(notification.severity, 0x808080),
            "fields": [
                {"name": str(k), "value": str(v), "inline": True}
                for k, v in notification.payload.items()
                if v is not None
            ],
        }
        payload = {"username": self._username, "embeds": [embed]}
        try:
            async with session.post(
                self._url, json=payload, timeout=aiohttp.ClientTimeout(total=self._timeout)
            ) as resp:
                if resp.status in (200, 204):
                    return True
                body = await resp.text()
                self.log.warning("discord_send_failed", status=resp.status, body=body[:200])
                return False
        except aiohttp.ClientError as exc:
            self.log.warning("discord_error", error=str(exc))
            return False

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()
            self._session = None


__all__ = ["DiscordNotifier"]
