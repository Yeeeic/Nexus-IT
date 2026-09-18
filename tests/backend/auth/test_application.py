import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from backend.app.audit import AuditEvent
from backend.app.auth.application import LoginApplicationService
from backend.app.auth.login import ActiveMembership, SessionCreation
from backend.app.auth.passwords import hash_password
from backend.app.auth.rate_limit import (
    LoginFailure,
    LoginPreflight,
    LoginRequestRateLimited,
)
from backend.app.auth.schemas import LoginRequest
from backend.app.auth.service import AuthenticationRejected, CredentialRecord


USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ORG_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
AUDIT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)
PASSWORD_HASH = hash_password("correct password")


class FakeRepository:
    def __init__(self) -> None:
        self.creation: SessionCreation | None = None
        self.audits: list[AuditEvent] = []
        self.committed = False
        self.rolled_back = False
        self.failed_email: str | None = None
        self.cleared_email: str | None = None

    async def __aenter__(self) -> "FakeRepository":
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        *_args: object,
    ) -> None:
        self.committed = exception_type is None
        self.rolled_back = exception_type is not None

    async def find_by_email(self, _email: str) -> CredentialRecord:
        return CredentialRecord(USER_ID, PASSWORD_HASH, True, None)

    async def list_active_for_user(
        self,
        _user_id: UUID,
    ) -> tuple[ActiveMembership, ...]:
        return (ActiveMembership(ORG_ID, "Org A"),)

    async def replace_for_login(
        self,
        creation: SessionCreation,
        *,
        previous_token_hash: bytes | None,
    ) -> None:
        self.creation = creation

    async def append_audit(self, event: AuditEvent) -> None:
        self.audits.append(event)

    async def record_credential_failure(
        self,
        normalized_email: str,
        *,
        now: datetime,
    ) -> None:
        assert now == NOW
        self.failed_email = normalized_email

    async def clear_credential_failures(self, normalized_email: str) -> None:
        self.cleared_email = normalized_email


class RepositoryFactory:
    def __init__(self) -> None:
        self.repositories: list[FakeRepository] = []

    def __call__(self) -> FakeRepository:
        repository = FakeRepository()
        self.repositories.append(repository)
        return repository


class FakeLimiter:
    def __init__(
        self,
        *,
        preflight: LoginPreflight | Exception = LoginPreflight(False, 0),
    ) -> None:
        self.preflight_result = preflight
        self.failures = 0
        self.successes = 0

    async def preflight(self, _email: str, _ip: str) -> LoginPreflight:
        if isinstance(self.preflight_result, Exception):
            raise self.preflight_result
        return self.preflight_result

    async def record_failure(self, _email: str, _ip: str) -> LoginFailure:
        self.failures += 1
        return LoginFailure(delay_seconds=0.5)

    async def record_success(self, _email: str, _ip: str) -> None:
        self.successes += 1


def _service(
    factory: RepositoryFactory,
    limiter: FakeLimiter,
    delays: list[float],
) -> LoginApplicationService:
    async def capture_delay(delay: float) -> None:
        delays.append(delay)

    return LoginApplicationService(
        repository_factory=factory,
        rate_limiter=limiter,  # type: ignore[arg-type]
        clock=lambda: NOW,
        sleeper=capture_delay,
        id_factory=lambda: AUDIT_ID,
    )


def test_success_commits_session_and_sanitized_audit_together() -> None:
    factory = RepositoryFactory()
    limiter = FakeLimiter()
    service = _service(factory, limiter, [])

    result = asyncio.run(
        service.login(
            LoginRequest(
                email="user@example.test",
                password="correct password",
            ),
            previous_session_token=None,
            user_agent="Browser/1.0",
            ip_address="192.0.2.10",
        )
    )

    repository = factory.repositories[0]
    assert repository.committed is True
    assert repository.creation is not None
    assert repository.audits[0].action == "AUTH.LOGIN_SUCCESS"
    assert repository.audits[0].organization_id == ORG_ID
    assert repository.audits[0].actor_id == USER_ID
    assert repository.cleared_email == "user@example.test"
    assert limiter.successes == 1
    assert result.user_id == USER_ID


def test_invalid_credentials_roll_back_then_commit_global_failure_audit() -> None:
    factory = RepositoryFactory()
    limiter = FakeLimiter()
    delays: list[float] = []
    service = _service(factory, limiter, delays)

    with pytest.raises(AuthenticationRejected):
        asyncio.run(
            service.login(
                LoginRequest(
                    email="user@example.test",
                    password="wrong password",
                ),
                previous_session_token="private-old-token",
                user_agent="Browser/1.0",
                ip_address="192.0.2.10",
            )
        )

    assert factory.repositories[0].rolled_back is True
    audit_repository = factory.repositories[1]
    assert audit_repository.committed is True
    event = audit_repository.audits[0]
    assert event.action == "AUTH.LOGIN_FAILURE"
    assert event.organization_id is None
    assert event.actor_id is None
    assert audit_repository.failed_email == "user@example.test"
    assert "user@example.test" not in repr(event)
    assert "wrong password" not in repr(event)
    assert "private-old-token" not in repr(event)
    assert delays == [0.5]
    assert limiter.failures == 1


def test_ip_limit_is_audited_without_opening_login_transaction() -> None:
    factory = RepositoryFactory()
    limiter = FakeLimiter(preflight=LoginRequestRateLimited(30))
    service = _service(factory, limiter, [])

    with pytest.raises(LoginRequestRateLimited):
        asyncio.run(
            service.login(
                LoginRequest(
                    email="user@example.test",
                    password="password",
                ),
                previous_session_token=None,
                user_agent=None,
                ip_address="192.0.2.10",
            )
        )

    assert len(factory.repositories) == 1
    assert factory.repositories[0].audits[0].action == "AUTH.LOGIN_BLOCKED"
    assert factory.repositories[0].audits[0].details == {
        "reason": "IP_RATE_LIMIT"
    }
