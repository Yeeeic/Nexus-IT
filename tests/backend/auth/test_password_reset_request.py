import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.app.audit import AuditEvent
from backend.app.auth.password_reset_request import PasswordResetRequestApplication


USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)
PEPPER = b"p" * 32


class AllowRequests:
    async def preflight(self, _account: str, _ip_address: str) -> object:
        return object()


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def send(self, email: str, token: str) -> None:
        self.calls.append((email, token))


class FakeRepository:
    def __init__(self, user_id: UUID | None) -> None:
        self.user_id = user_id
        self.created: tuple[UUID, UUID, bytes, datetime, datetime] | None = None
        self.audits: list[AuditEvent] = []

    async def __aenter__(self) -> "FakeRepository":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def find_active_reset_user_id(self, _email: str) -> UUID | None:
        return self.user_id

    async def replace_password_reset_token(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self.created = (token_id, user_id, token_hash, created_at, expires_at)

    async def append_audit(self, event: AuditEvent) -> None:
        self.audits.append(event)


def _application(repository: FakeRepository, notifier: FakeNotifier) -> PasswordResetRequestApplication:
    return PasswordResetRequestApplication(
        lambda: repository,
        pepper=PEPPER,
        request_guard=AllowRequests(),
        notifier=notifier,
        clock=lambda: NOW,
    )


def test_existing_user_gets_one_time_delivery_after_hashed_storage() -> None:
    repository = FakeRepository(USER_ID)
    notifier = FakeNotifier()
    application = _application(repository, notifier)

    delivery = asyncio.run(
        application.request(
            "user@example.test",
            ip_address="192.0.2.10",
            user_agent="Browser/1.0",
        )
    )

    assert delivery is not None
    assert repository.created is not None
    assert repository.created[1] == USER_ID
    assert len(repository.created[2]) == 32
    assert repository.created[3] == NOW
    assert repository.created[4] == NOW + timedelta(minutes=15)
    assert delivery.token not in repr(delivery)
    assert delivery.token.encode() not in repository.created[2]
    assert repository.audits[0].action == "AUTH.PASSWORD_RESET_REQUESTED"
    assert notifier.calls == []

    asyncio.run(application.deliver(delivery))

    assert notifier.calls == [("user@example.test", delivery.token)]


def test_unknown_user_returns_same_empty_delivery_without_creating_token() -> None:
    repository = FakeRepository(None)
    notifier = FakeNotifier()
    application = _application(repository, notifier)

    delivery = asyncio.run(
        application.request(
            "missing@example.test",
            ip_address="192.0.2.10",
            user_agent=None,
        )
    )

    assert delivery is None
    assert repository.created is None
    assert notifier.calls == []
