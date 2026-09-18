import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.app.auth.session import (
    CsrfRejected,
    SessionAuthenticationService,
    SessionRecord,
    SessionRejected,
)
from backend.app.auth.session_tokens import hash_token


SESSION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ORG_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)
SESSION_TOKEN = "valid-session-token"
CSRF_TOKEN = "valid-csrf-token"


class Repository:
    def __init__(self, record: SessionRecord | None) -> None:
        self.record = record
        self.requested_hash: bytes | None = None
        self.touch: tuple[UUID, UUID, datetime, datetime] | None = None

    async def find_by_token_hash(self, token_hash: bytes) -> SessionRecord | None:
        self.requested_hash = token_hash
        return self.record

    async def touch_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        last_seen_at: datetime,
        expires_at: datetime,
    ) -> None:
        self.touch = (session_id, user_id, last_seen_at, expires_at)


def _record(**changes: object) -> SessionRecord:
    values: dict[str, object] = {
        "session_id": SESSION_ID,
        "organization_id": ORG_ID,
        "user_id": USER_ID,
        "csrf_token_hash": hash_token(CSRF_TOKEN),
        "expires_at": NOW + timedelta(minutes=30),
        "last_seen_at": NOW - timedelta(minutes=30),
        "is_revoked": False,
        "created_at": NOW - timedelta(days=1),
    }
    values.update(changes)
    return SessionRecord(**values)  # type: ignore[arg-type]


def test_authenticate_derives_identity_and_renews_bounded_expiry() -> None:
    repository = Repository(
        _record(created_at=NOW - timedelta(days=6, hours=23, minutes=30))
    )
    service = SessionAuthenticationService(repository)

    identity = asyncio.run(
        service.authenticate(
            SESSION_TOKEN,
            now=NOW,
            require_organization=True,
        )
    )

    assert identity.session_id == SESSION_ID
    assert identity.user_id == USER_ID
    assert identity.organization_id == ORG_ID
    assert repository.requested_hash == hash_token(SESSION_TOKEN)
    assert repository.touch == (
        SESSION_ID,
        USER_ID,
        NOW,
        NOW + timedelta(minutes=30),
    )


@pytest.mark.parametrize(
    "record",
    [
        None,
        _record(is_revoked=True),
        _record(expires_at=NOW),
        _record(last_seen_at=NOW - timedelta(hours=1)),
        _record(created_at=NOW - timedelta(days=7)),
        _record(organization_id=None),
    ],
)
def test_private_authentication_uniformly_rejects_invalid_sessions(
    record: SessionRecord | None,
) -> None:
    repository = Repository(record)
    service = SessionAuthenticationService(repository)

    with pytest.raises(SessionRejected):
        asyncio.run(
            service.authenticate(
                SESSION_TOKEN,
                now=NOW,
                require_organization=True,
            )
        )

    assert repository.touch is None


def test_pending_session_is_valid_only_for_context_selection() -> None:
    repository = Repository(_record(organization_id=None))

    identity = asyncio.run(
        SessionAuthenticationService(repository).authenticate(
            SESSION_TOKEN,
            now=NOW,
            require_organization=False,
        )
    )

    assert identity.organization_id is None


@pytest.mark.parametrize(
    ("cookie", "header"),
    [
        (None, CSRF_TOKEN),
        (CSRF_TOKEN, None),
        ("wrong", CSRF_TOKEN),
        (CSRF_TOKEN, "wrong"),
    ],
)
def test_csrf_requires_matching_cookie_header_and_stored_hash(
    cookie: str | None,
    header: str | None,
) -> None:
    identity = asyncio.run(
        SessionAuthenticationService(Repository(_record())).authenticate(
            SESSION_TOKEN,
            now=NOW,
            require_organization=True,
        )
    )

    with pytest.raises(CsrfRejected):
        identity.verify_csrf(cookie=cookie, header=header)


def test_csrf_accepts_only_both_valid_copies() -> None:
    identity = asyncio.run(
        SessionAuthenticationService(Repository(_record())).authenticate(
            SESSION_TOKEN,
            now=NOW,
            require_organization=True,
        )
    )

    identity.verify_csrf(cookie=CSRF_TOKEN, header=CSRF_TOKEN)
