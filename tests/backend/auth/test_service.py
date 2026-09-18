from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.app.auth.passwords import hash_password
from backend.app.auth.schemas import LoginRequest
from backend.app.auth.service import (
    AuthenticatedIdentity,
    AuthenticationRejected,
    AuthenticationService,
    CredentialRecord,
)


USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PASSWORD_HASH = hash_password("correct password")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)


class MemoryCredentialReader:
    def __init__(self, record: CredentialRecord | None) -> None:
        self.record = record
        self.requested_email: str | None = None

    def find_by_email(self, normalized_email: str) -> CredentialRecord | None:
        self.requested_email = normalized_email
        return self.record


def test_authenticate_returns_only_global_identity_for_valid_credentials() -> None:
    reader = MemoryCredentialReader(
        CredentialRecord(
            user_id=USER_ID,
            password_hash=PASSWORD_HASH,
            is_active=True,
            locked_until=None,
        )
    )
    service = AuthenticationService(reader)

    identity = service.authenticate(
        LoginRequest(email=" USER@EXAMPLE.COM ", password="correct password"),
        now=NOW,
    )

    assert identity == AuthenticatedIdentity(user_id=USER_ID)
    assert reader.requested_email == "user@example.com"


@pytest.mark.parametrize(
    "record,password",
    [
        (None, "wrong password"),
        (
            CredentialRecord(USER_ID, PASSWORD_HASH, True, None),
            "wrong password",
        ),
        (
            CredentialRecord(USER_ID, PASSWORD_HASH, False, None),
            "correct password",
        ),
        (
            CredentialRecord(
                USER_ID,
                PASSWORD_HASH,
                True,
                NOW + timedelta(minutes=1),
            ),
            "correct password",
        ),
        (
            CredentialRecord(USER_ID, "malformed-hash", True, None),
            "correct password",
        ),
    ],
)
def test_authenticate_uses_one_rejection_for_every_invalid_state(
    record: CredentialRecord | None,
    password: str,
) -> None:
    service = AuthenticationService(MemoryCredentialReader(record))

    with pytest.raises(AuthenticationRejected) as error:
        service.authenticate(
            LoginRequest(email="user@example.com", password=password),
            now=NOW,
        )

    assert error.value.code == "INVALID_CREDENTIALS"
    assert str(error.value) == "Credenciales inválidas o acceso no autorizado"
    assert password not in repr(error.value)
