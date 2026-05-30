"""Telegram notifier via the Bot API."""

from __future__ import annotations

import aiohttp

from quantbot.core.constants import NotificationChannel
from quantbot.notifications.base import Notification, Notifier


class TelegramNotifier(Notifier):
    """Send notifications to a Telegram chat via a bot token."""

    channel = NotificationChannel.TELEGRAM

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        session: aiohttp.ClientSession | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._session = session
        self._owns_session = session is None
        self._timeout = timeout

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def send(self, notification: Notification) -> bool:
        session = await self._ensure_session()
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": notification.as_text(),
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=self._timeout)
            ) as resp:
                if resp.status == 200:
                    return True
                body = await resp.text()
                self.log.warning("telegram_send_failed", status=resp.status, body=body[:200])
                return False
        except aiohttp.ClientError as exc:
            self.log.warning("telegram_error", error=str(exc))
            return False

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()
            self._session = None


__all__ = ["TelegramNotifier"]
