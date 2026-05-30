"""Email notifier via async SMTP (aiosmtplib, optional dependency)."""

from __future__ import annotations

from email.message import EmailMessage

from quantbot.core.constants import NotificationChannel
from quantbot.core.exceptions import DependencyError
from quantbot.notifications.base import Notification, Notifier


class EmailNotifier(Notifier):
    """Send notifications by email over SMTP with STARTTLS."""

    channel = NotificationChannel.EMAIL

    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        sender: str,
        recipients: list[str],
        use_tls: bool = True,
        timeout: float = 15.0,
    ) -> None:
        self._host = smtp_host
        self._port = smtp_port
        self._username = username
        self._password = password
        self._sender = sender or username
        self._recipients = recipients
        self._use_tls = use_tls
        self._timeout = timeout

    async def send(self, notification: Notification) -> bool:
        aiosmtplib = _import_aiosmtplib()
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = ", ".join(self._recipients)
        message["Subject"] = f"[QuantBot] {notification.title}"
        message.set_content(self._render(notification))
        try:
            await aiosmtplib.send(
                message,
                hostname=self._host,
                port=self._port,
                username=self._username or None,
                password=self._password or None,
                start_tls=self._use_tls,
                timeout=self._timeout,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - SMTP raises many error types
            self.log.warning("email_send_failed", error=str(exc))
            return False

    @staticmethod
    def _render(notification: Notification) -> str:
        lines = [notification.title, "", notification.message, ""]
        for key, value in notification.payload.items():
            lines.append(f"{key}: {value}")
        lines += ["", f"Severity: {notification.severity.value}", "—", "QuantBot"]
        return "\n".join(lines)


def _import_aiosmtplib():
    try:
        import aiosmtplib  # type: ignore

        return aiosmtplib
    except ImportError as exc:  # pragma: no cover
        raise DependencyError(
            "Email notifications require aiosmtplib. Install: pip install 'quantbot[notify]'"
        ) from exc


__all__ = ["EmailNotifier"]
