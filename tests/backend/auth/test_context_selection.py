import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.app.audit import AuditEvent
from backend.app.auth.context import (
    ContextSelectionRejected,
    ContextSelectionService,
)
from backend.app.auth.login import ActiveMembership, SessionCreation
from backend.app.auth.session import SessionRecord
from backend.app.auth.session_tokens import SessionSecrets, hash_token


SESSION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
NEW_SESSION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
USER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ORG_A = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
ORG_B = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
AUDIT_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)
SESSION_TOKEN = "pending-session-token"
CSRF_TOKEN = "pending-csrf-token"
NEW_SECRETS = SessionSecrets(
    session_id=NEW_SESSION_ID,
    session_token="new-fixed-session-token",
    session_token_hash=hash_token("new-fixed-session-token"),
    csrf_token="new-fixed-csrf-token",
    csrf_token_hash=hash_token("new-fixed-csrf-token"),
)


class Repository:
    def __init__(self) -> None:
        self.creation: SessionCreation | None = None
        self.previous_hash: bytes | None = None
        self.audit: AuditEvent | None = None

    async def find_by_token_hash(self, _token_hash: bytes) -> SessionRecord:
        return SessionRecord(
            session_id=SESSION_ID,
            organization_id=None,
            user_id=USER_ID,
            csrf_token_hash=hash_token(CSRF_TOKEN),
            expires_at=NOW + timedelta(minutes=30),
            last_seen_at=NOW - timedelta(minutes=5),
            is_revoked=False,
            created_at=NOW - timedelta(hours=1),
        )

    async def touch_session(self, **_values: object) -> None:
        return None

    async def list_active_for_user(
        self,
        _user_id: UUID,
    ) -> tuple[ActiveMembership, ...]:
        return (
            ActiveMembership(ORG_A, "Org A"),
            ActiveMembership(ORG_B, "Org B"),
        )

    async def replace_for_login(
        self,
        creation: SessionCreation,
        *,
        previous_token_hash: bytes | None,
    ) -> None:
        self.creation = creation
        self.previous_hash = previous_token_hash

    async def append_audit(self, event: AuditEvent) -> None:
        self.audit = event


def _service(repository: Repository) -> ContextSelectionService:
    return ContextSelectionService(
        repository=repository,
        issue_secrets=lambda: NEW_SECRETS,
        id_factory=lambda: AUDIT_ID,
    )


def test_selection_accepts_only_active_membership_and_rotates_session() -> None:
    repository = Repository()

    result = asyncio.run(
        _service(repository).select(
            session_token=SESSION_TOKEN,
            csrf_cookie=CSRF_TOKEN,
            csrf_header=CSRF_TOKEN,
            organization_id=ORG_B,
            now=NOW,
            user_agent="Browser/1.0",
            ip_address="192.0.2.10",
        )
    )

    assert result.organization_id == ORG_B
    assert result.secrets is NEW_SECRETS
    assert repository.previous_hash == hash_token(SESSION_TOKEN)
    assert repository.creation is not None
    assert repository.creation.session_id == NEW_SESSION_ID
    assert repository.creation.organization_id == ORG_B
    assert repository.audit is not None
    assert repository.audit.action == "AUTH.CONTEXT_SELECTED"
    assert repository.audit.organization_id == ORG_B
    assert SESSION_TOKEN not in repr(repository.audit)
    assert CSRF_TOKEN not in repr(repository.audit)


def test_selection_rejects_organization_outside_memberships_without_rotation() -> None:
    repository = Repository()
    unknown = UUID("11111111-1111-4111-8111-111111111111")

    with pytest.raises(ContextSelectionRejected):
        asyncio.run(
            _service(repository).select(
                session_token=SESSION_TOKEN,
                csrf_cookie=CSRF_TOKEN,
                csrf_header=CSRF_TOKEN,
                organization_id=unknown,
                now=NOW,
                user_agent=None,
                ip_address="192.0.2.10",
            )
        )

    assert repository.creation is None
    assert repository.audit is None
