import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.app.audit import AuditEvent
from backend.app.auth.logout import LogoutService
from backend.app.auth.session import CsrfRejected, SessionRecord
from backend.app.auth.session_tokens import hash_token


SESSION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ORG_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
AUDIT_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)
SESSION_TOKEN = "valid-session-token"
CSRF_TOKEN = "valid-csrf-token"


class Repository:
    def __init__(self, organization_id: UUID | None = ORG_ID) -> None:
        self.organization_id = organization_id
        self.revoked: tuple[UUID, UUID] | None = None
        self.audit: AuditEvent | None = None

    async def find_by_token_hash(self, _token_hash: bytes) -> SessionRecord:
        return SessionRecord(
            session_id=SESSION_ID,
            organization_id=self.organization_id,
            user_id=USER_ID,
            csrf_token_hash=hash_token(CSRF_TOKEN),
            expires_at=NOW + timedelta(minutes=30),
            last_seen_at=NOW - timedelta(minutes=5),
            is_revoked=False,
            created_at=NOW - timedelta(hours=1),
        )

    async def touch_session(self, **_values: object) -> None:
        return None

    async def revoke_current_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> None:
        self.revoked = (session_id, user_id)

    async def append_audit(self, event: AuditEvent) -> None:
        self.audit = event


def test_logout_revokes_and_audits_tenant_session() -> None:
    repository = Repository()

    asyncio.run(
        LogoutService(repository=repository, id_factory=lambda: AUDIT_ID).logout(
            session_token=SESSION_TOKEN,
            csrf_cookie=CSRF_TOKEN,
            csrf_header=CSRF_TOKEN,
            now=NOW,
            user_agent="Browser/1.0",
            ip_address="192.0.2.10",
        )
    )

    assert repository.revoked == (SESSION_ID, USER_ID)
    assert repository.audit is not None
    assert repository.audit.action == "AUTH.LOGOUT"
    assert repository.audit.organization_id == ORG_ID
    assert repository.audit.actor_id == USER_ID
    assert SESSION_TOKEN not in repr(repository.audit)
    assert CSRF_TOKEN not in repr(repository.audit)


def test_logout_supports_pending_session_without_inventing_tenant() -> None:
    repository = Repository(organization_id=None)

    asyncio.run(
        LogoutService(repository=repository, id_factory=lambda: AUDIT_ID).logout(
            session_token=SESSION_TOKEN,
            csrf_cookie=CSRF_TOKEN,
            csrf_header=CSRF_TOKEN,
            now=NOW,
            user_agent=None,
            ip_address="192.0.2.10",
        )
    )

    assert repository.audit is not None
    assert repository.audit.organization_id is None


def test_logout_rejects_missing_csrf_before_revocation() -> None:
    repository = Repository()

    with pytest.raises(CsrfRejected):
        asyncio.run(
            LogoutService(repository=repository).logout(
                session_token=SESSION_TOKEN,
                csrf_cookie=CSRF_TOKEN,
                csrf_header=None,
                now=NOW,
                user_agent=None,
                ip_address="192.0.2.10",
            )
        )

    assert repository.revoked is None
    assert repository.audit is None
