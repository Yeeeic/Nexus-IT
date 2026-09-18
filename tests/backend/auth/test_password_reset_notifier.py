import asyncio

from backend.app.auth.password_reset_notifier import SmtpPasswordResetNotifier
from backend.app.core.config import EmailSettings


class FakeSmtp:
    def __init__(self) -> None:
        self.started_tls = False
        self.login_call: tuple[str, str] | None = None
        self.message: object | None = None

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def starttls(self, *, context: object) -> None:
        assert context is not None
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.login_call = (username, password)

    def send_message(self, message: object) -> None:
        self.message = message


def test_smtp_notifier_requires_tls_and_places_token_only_in_message() -> None:
    fake = FakeSmtp()
    settings = EmailSettings.from_environment(
        {
            "NEXUS_SMTP_HOST": "smtp.example.test",
            "NEXUS_SMTP_PORT": "587",
            "NEXUS_SMTP_USERNAME": "nexus@example.test",
            "NEXUS_SMTP_PASSWORD": "smtp-runtime-password",
            "NEXUS_SMTP_FROM": "nexus@example.test",
            "NEXUS_PASSWORD_RESET_URL": "https://app.example.test/reset-password",
        }
    )
    notifier = SmtpPasswordResetNotifier(
        settings,
        transport_factory=lambda *_args, **_kwargs: fake,
    )

    asyncio.run(notifier.send("user@example.test", "id.private-secret"))

    assert fake.started_tls is True
    assert fake.login_call == ("nexus@example.test", "smtp-runtime-password")
    assert fake.message is not None
    message_text = str(fake.message)
    assert "user@example.test" in message_text
    assert "token=id.private-secret" in message_text
    assert "private-secret" not in repr(notifier)
