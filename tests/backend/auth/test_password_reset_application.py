import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.app.audit import AuditEvent
from backend.app.auth.password_reset import (
    PasswordResetApplication,
    PasswordResetRecord,
    PasswordResetRejected,
    PasswordResetToken,
)
from backend.app.auth.rate_limit import LoginRequestRateLimited


USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)
PEPPER = b"p" * 32


class AllowRequests:
    async def preflight(self, _account: str, _ip_address: str) -> object:
        return object()


class RejectRequests:
    async def preflight(self, _account: str, _ip_address: str) -> object:
        raise LoginRequestRateLimited(30)


def _service(factory: object) -> PasswordResetApplication:
    return PasswordResetApplication(
        factory,  # type: ignore[arg-type]
        pepper=PEPPER,
        request_guard=AllowRequests(),
        clock=lambda: NOW,
    )


async def _consume(service: PasswordResetApplication, token: str) -> None:
    await service.consume(
        token,
        "New secure password 123",
        ip_address="192.0.2.10",
    )


class FakeRepository:
    def __init__(self, record: PasswordResetRecord | None) -> None:
        self.record = record
        self.consumed: tuple[UUID, UUID, str, datetime] | None = None
        self.audits: list[AuditEvent] = []
        self.committed = False
        self.rolled_back = False
        self.fail_consume = False

    async def __aenter__(self) -> "FakeRepository":
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        *_args: object,
    ) -> None:
        self.committed = exception_type is None
        self.rolled_back = exception_type is not None

    async def lock_password_reset_token(
        self, token_id: UUID
    ) -> PasswordResetRecord | None:
        return self.record if self.record and self.record.token_id == token_id else None

    async def consume_password_reset(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        password_hash: str,
        used_at: datetime,
    ) -> None:
        if self.fail_consume:
            raise RuntimeError("forced database failure")
        self.consumed = (token_id, user_id, password_hash, used_at)

    async def append_audit(self, event: AuditEvent) -> None:
        self.audits.append(event)


class Factory:
    def __init__(self, record: PasswordResetRecord | None) -> None:
        self.record = record
        self.repositories: list[FakeRepository] = []

    def __call__(self) -> FakeRepository:
        repository = FakeRepository(self.record)
        self.repositories.append(repository)
        return repository


def _record(token: PasswordResetToken, **changes: object) -> PasswordResetRecord:
    values = {
        "token_id": token.token_id,
        "user_id": USER_ID,
        "secret_hash": token.secret_hash,
        "expires_at": NOW + timedelta(minutes=15),
        "used_at": None,
        "is_revoked": False,
    }
    values.update(changes)
    return PasswordResetRecord(**values)  # type: ignore[arg-type]


def test_valid_token_updates_password_and_revokes_related_credentials() -> None:
    token = PasswordResetToken.generate(PEPPER)
    factory = Factory(_record(token))
    service = _service(factory)

    asyncio.run(_consume(service, token.value))

    repository = factory.repositories[0]
    assert repository.committed is True
    assert repository.consumed is not None
    assert repository.consumed[0:2] == (token.token_id, USER_ID)
    assert repository.consumed[2].startswith("$argon2id$")
    assert repository.consumed[3] == NOW
    assert repository.audits[0].action == "AUTH.PASSWORD_RESET_SUCCESS"
    assert token.value not in repr(repository.audits[0])


@pytest.mark.parametrize(
    "change",
    [
        {"expires_at": NOW},
        {"used_at": NOW - timedelta(minutes=1)},
        {"is_revoked": True},
    ],
)
def test_invalid_token_state_rolls_back_without_mutation(change: dict[str, object]) -> None:
    token = PasswordResetToken.generate(PEPPER)
    factory = Factory(_record(token, **change))
    service = _service(factory)

    with pytest.raises(PasswordResetRejected):
        asyncio.run(_consume(service, token.value))

    assert factory.repositories[0].rolled_back is True
    assert factory.repositories[0].consumed is None


def test_wrong_secret_rolls_back_without_consuming_token() -> None:
    token = PasswordResetToken.generate(PEPPER)
    wrong = PasswordResetToken.generate(PEPPER)
    factory = Factory(_record(token))
    service = _service(factory)

    with pytest.raises(PasswordResetRejected):
        asyncio.run(
            _consume(
                service,
                f"{token.token_id}.{wrong.value.split('.', 1)[1]}",
            )
        )

    assert factory.repositories[0].rolled_back is True
    assert factory.repositories[0].consumed is None


def test_database_failure_rolls_back_token_and_password_together() -> None:
    token = PasswordResetToken.generate(PEPPER)
    factory = Factory(_record(token))
    repository = factory()
    repository.fail_consume = True
    factory.repositories.clear()
    service = _service(lambda: repository)

    with pytest.raises(Exception):
        asyncio.run(_consume(service, token.value))

    assert repository.rolled_back is True
    assert repository.consumed is None


def test_rate_limit_rejects_before_opening_database_transaction() -> None:
    token = PasswordResetToken.generate(PEPPER)
    factory = Factory(_record(token))
    service = PasswordResetApplication(
        factory,
        pepper=PEPPER,
        request_guard=RejectRequests(),
        clock=lambda: NOW,
    )

    with pytest.raises(LoginRequestRateLimited):
        asyncio.run(_consume(service, token.value))

    assert factory.repositories == []
