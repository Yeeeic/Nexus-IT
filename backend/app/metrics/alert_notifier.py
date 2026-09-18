"""TLS-only email notifications for triggered alerts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from email.message import EmailMessage
import logging
import smtplib
import ssl
from typing import Protocol

from backend.app.core.config import EmailSettings
from backend.app.metrics.service import AlertSummary

logger = logging.getLogger("nexus.alerts.email")


class SmtpTransport(Protocol):
    def __enter__(self) -> "SmtpTransport": ...
    def __exit__(self, *args: object) -> None: ...
    def starttls(self, *, context: ssl.SSLContext) -> None: ...
    def login(self, username: str, password: str) -> None: ...
    def send_message(self, message: EmailMessage) -> None: ...


TransportFactory = Callable[..., SmtpTransport]


class SmtpAlertNotifier:
    def __init__(
        self,
        settings: EmailSettings,
        *,
        transport_factory: TransportFactory = smtplib.SMTP,
    ) -> None:
        self._settings = settings
        self._transport_factory = transport_factory

    async def notify(
        self,
        recipients: Sequence[str],
        alert: AlertSummary,
    ) -> None:
        if not recipients:
            return
        await asyncio.to_thread(self._send_sync, tuple(recipients), alert)

    def _send_sync(
        self,
        recipients: tuple[str, ...],
        alert: AlertSummary,
    ) -> None:
        message = EmailMessage()
        message["Subject"] = f"[{alert.severity}] Alerta NEXUS IT: {alert.message[:80]}"
        message["From"] = self._settings.sender
        message["To"] = ", ".join(recipients)
        body = (
            f"Alerta del Sistema NEXUS IT\n\n"
            f"Severidad: {alert.severity}\n"
            f"Dispositivo: {alert.device_id}\n"
            f"Estado: {alert.status}\n"
            f"Mensaje: {alert.message}\n"
            f"Hora: {alert.triggered_at.isoformat()}\n\n"
            f"Acceda al panel de NEXUS IT para gestionar esta alerta."
        )
        message.set_content(body)

        try:
            with self._transport_factory(
                self._settings.host,
                self._settings.port,
                timeout=10,
            ) as transport:
                transport.starttls(context=ssl.create_default_context())
                transport.login(
                    self._settings.username,
                    self._settings.password.get_secret_value(),
                )
                transport.send_message(message)
        except Exception as exc:
            logger.warning("No se pudo enviar notificación de alerta por correo: %s", exc)

    def __repr__(self) -> str:
        return f"SmtpAlertNotifier(host={self._settings.host!r})"
