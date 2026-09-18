"""TLS-only password-reset email delivery."""

import asyncio
from collections.abc import Callable
from email.message import EmailMessage
import smtplib
import ssl
from typing import Protocol
from urllib.parse import urlencode

from backend.app.core.config import EmailSettings


class SmtpTransport(Protocol):
    def __enter__(self) -> "SmtpTransport": ...
    def __exit__(self, *args: object) -> None: ...
    def starttls(self, *, context: ssl.SSLContext) -> None: ...
    def login(self, username: str, password: str) -> None: ...
    def send_message(self, message: EmailMessage) -> None: ...


TransportFactory = Callable[..., SmtpTransport]


class SmtpPasswordResetNotifier:
    def __init__(
        self,
        settings: EmailSettings,
        *,
        transport_factory: TransportFactory = smtplib.SMTP,
    ) -> None:
        self._settings = settings
        self._transport_factory = transport_factory

    async def send(self, recipient: str, token: str) -> None:
        await asyncio.to_thread(self._send, recipient, token)

    def _send(self, recipient: str, token: str) -> None:
        separator = "&" if "?" in self._settings.password_reset_url else "?"
        reset_url = (
            f"{self._settings.password_reset_url}{separator}"
            f"{urlencode({'token': token})}"
        )
        message = EmailMessage()
        message["Subject"] = "Restablece tu contraseÃ±a de NEXUS IT"
        message["From"] = self._settings.sender
        message["To"] = recipient
        message.set_content(
            "Usa este enlace dentro de 15 minutos:\n"
            f"{reset_url}\n\n"
            "Si no solicitaste el cambio, ignora este mensaje."
        )

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

    def __repr__(self) -> str:
        return f"SmtpPasswordResetNotifier(host={self._settings.host!r})"
