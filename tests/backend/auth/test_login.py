import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.app.auth.login import (
    ActiveMembership,
    AsyncLoginCoordinator,
    LoginCoordinator,
    LoginStatus,
    SessionCreation,
)
from backend.app.auth.passwords import hash_password
from backend.app.auth.schemas import LoginRequest
from backend.app.auth.service import (
    AuthenticationRejected,
    AuthenticationService,
    CredentialRecord,
)
from backend.app.auth.session_tokens import SessionSecrets, hash_token


USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ORG_A = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ORG_B = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
SESSION_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)
PASSWORD_HASH = hash_password("correct password")
SECRETS = SessionSecrets(
    session_id=SESSION_ID,
    session_token="new-session-token",
    session_token_hash=hash_token("new-session-token"),
    csrf_token="new-csrf-token",
    csrf_token_hash=hash_token("new-csrf-token"),
)


class CredentialReader:
    def find_by_email(self, _normalized_email: str) -> CredentialRecord:
        return CredentialRecord(
            user_id=USER_ID,
            password_hash=PASSWORD_HASH,
            is_active=True,
            locked_until=None,
        )


class MembershipReader:
    def __init__(self, memberships: tuple[ActiveMembership, ...]) -> None:
        self.memberships = memberships
        self.requested_user_id: UUID | None = None

    def list_active_for_user(self, user_id: UUID) -> tuple[ActiveMembership, ...]:
        self.requested_user_id = user_id
        return self.memberships


class SessionStore:
    def __init__(self) -> None:
        self.creation: SessionCreation | None = None
        self.previous_token_hash: bytes | None = None

    def replace_for_login(
        self,
        creation: SessionCreation,
        *,
        previous_token_hash: bytes | None,
    ) -> None:
        self.creation = creation
        self.previous_token_hash = previous_token_hash


class AsyncRepository:
    def __init__(self) -> None:
        self.creation: SessionCreation | None = None

    async def find_by_email(self, _normalized_email: str) -> CredentialRecord:
        return CredentialRecord(
            user_id=USER_ID,
            password_hash=PASSWORD_HASH,
            is_active=True,
            locked_until=None,
        )

    async def list_active_for_user(
        self,
        _user_id: UUID,
    ) -> tuple[ActiveMembership, ...]:
        return (
            ActiveMembership(organization_id=ORG_A, organization_name="Org A"),
        )

    async def replace_for_login(
        self,
        creation: SessionCreation,
        *,
        previous_token_hash: bytes | None,
    ) -> None:
        assert previous_token_hash is None
        self.creation = creation


def _coordinator(
    memberships: tuple[ActiveMembership, ...],
) -> tuple[LoginCoordinator, MembershipReader, SessionStore]:
    membership_reader = MembershipReader(memberships)
    session_store = SessionStore()
    coordinator = LoginCoordinator(
        authentication=AuthenticationService(CredentialReader()),
        membership_reader=membership_reader,
        session_store=session_store,
        issue_secrets=lambda: SECRETS,
    )
    return coordinator, membership_reader, session_store


def test_login_derives_single_organization_and_regenerates_session() -> None:
    coordinator, membership_reader, session_store = _coordinator(
        (ActiveMembership(organization_id=ORG_A, organization_name="Org A"),)
    )

    result = coordinator.login(
        LoginRequest(email="user@example.test", password="correct password"),
        now=NOW,
        previous_session_token="attacker-fixed-token",
        user_agent=" Browser/1.0 ",
        ip_address="192.0.2.10",
    )

    assert result.status is LoginStatus.AUTHENTICATED
    assert result.organizations == ()
    assert result.secrets is SECRETS
    assert membership_reader.requested_user_id == USER_ID
    assert session_store.previous_token_hash == hash_token("attacker-fixed-token")
    assert session_store.creation == SessionCreation(
        session_id=SESSION_ID,
        user_id=USER_ID,
        organization_id=ORG_A,
        session_token_hash=SECRETS.session_token_hash,
        csrf_token_hash=SECRETS.csrf_token_hash,
        expires_at=NOW + timedelta(hours=1),
        last_seen_at=NOW,
        user_agent="Browser/1.0",
        ip_address="192.0.2.10",
    )


def test_login_with_multiple_memberships_creates_pending_session() -> None:
    memberships = (
        ActiveMembership(organization_id=ORG_A, organization_name="Org A"),
        ActiveMembership(organization_id=ORG_B, organization_name="Org B"),
    )
    coordinator, _, session_store = _coordinator(memberships)

    result = coordinator.login(
        LoginRequest(email="user@example.test", password="correct password"),
        now=NOW,
    )

    assert result.status is LoginStatus.ORGANIZATION_SELECTION_REQUIRED
    assert result.organizations == memberships
    assert session_store.creation is not None
    assert session_store.creation.organization_id is None


def test_login_rejects_identity_without_active_membership() -> None:
    coordinator, _, session_store = _coordinator(())

    with pytest.raises(AuthenticationRejected):
        coordinator.login(
            LoginRequest(email="user@example.test", password="correct password"),
            now=NOW,
        )

    assert session_store.creation is None


def test_login_bounds_untrusted_user_agent_before_persistence() -> None:
    coordinator, _, session_store = _coordinator(
        (ActiveMembership(organization_id=ORG_A, organization_name="Org A"),)
    )

    coordinator.login(
        LoginRequest(email="user@example.test", password="correct password"),
        now=NOW,
        user_agent="x" * 500,
    )

    assert session_store.creation is not None
    assert session_store.creation.user_agent == "x" * 255


def test_login_rejects_invalid_derived_ip_address() -> None:
    coordinator, _, session_store = _coordinator(
        (ActiveMembership(organization_id=ORG_A, organization_name="Org A"),)
    )

    with pytest.raises(ValueError):
        coordinator.login(
            LoginRequest(email="user@example.test", password="correct password"),
            now=NOW,
            ip_address="not-an-ip-address",
        )

    assert session_store.creation is None


def test_login_result_representation_redacts_session_tokens() -> None:
    coordinator, _, _ = _coordinator(
        (ActiveMembership(organization_id=ORG_A, organization_name="Org A"),)
    )

    result = coordinator.login(
        LoginRequest(email="user@example.test", password="correct password"),
        now=NOW,
    )

    assert SECRETS.session_token not in repr(result)
    assert SECRETS.csrf_token not in repr(result)


def test_async_login_coordinates_repository_without_blocking_database_io() -> None:
    repository = AsyncRepository()
    coordinator = AsyncLoginCoordinator(
        repository=repository,
        issue_secrets=lambda: SECRETS,
    )

    result = asyncio.run(
        coordinator.login(
            LoginRequest(
                email="user@example.test",
                password="correct password",
            ),
            now=NOW,
            ip_address="192.0.2.10",
        )
    )

    assert result.status is LoginStatus.AUTHENTICATED
    assert repository.creation is not None
    assert repository.creation.organization_id == ORG_A


def test_async_login_forces_uniform_rejection_for_redis_credential_lock() -> None:
    repository = AsyncRepository()
    coordinator = AsyncLoginCoordinator(repository=repository)

    with pytest.raises(AuthenticationRejected):
        asyncio.run(
            coordinator.login(
                LoginRequest(
                    email="user@example.test",
                    password="correct password",
                ),
                now=NOW,
                force_rejection=True,
            )
        )

    assert repository.creation is None
