"""Credential authentication without tenant selection or session creation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.app.auth.passwords import hash_password, verify_password
from backend.app.auth.schemas import LoginRequest


INVALID_CREDENTIALS_MESSAGE = "Credenciales inválidas o acceso no autorizado"
_DUMMY_PASSWORD_HASH = hash_password("nexus-dummy-password-for-timing-equality")


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    user_id: UUID
    password_hash: str
    is_active: bool
    locked_until: datetime | None


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    user_id: UUID


class CredentialReader(Protocol):
    def find_by_email(self, normalized_email: str) -> CredentialRecord | None: ...


class AuthenticationRejected(Exception):
    code = "INVALID_CREDENTIALS"

    def __init__(self) -> None:
        super().__init__(INVALID_CREDENTIALS_MESSAGE)


def authenticate_credential(
    request: LoginRequest,
    record: CredentialRecord | None,
    *,
    now: datetime,
) -> AuthenticatedIdentity:
    """Verify a loaded credential while preserving uniform rejection behavior."""
    encoded_hash = record.password_hash if record else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(
        request.password.get_secret_value(),
        encoded_hash,
    )
    is_locked = bool(record and record.locked_until and record.locked_until > now)

    if not record or not password_matches or not record.is_active or is_locked:
        raise AuthenticationRejected

    return AuthenticatedIdentity(user_id=record.user_id)


class AuthenticationService:
    def __init__(self, credential_reader: CredentialReader) -> None:
        self._credential_reader = credential_reader

    def authenticate(
        self,
        request: LoginRequest,
        *,
        now: datetime,
    ) -> AuthenticatedIdentity:
        record = self._credential_reader.find_by_email(request.email)
        return authenticate_credential(request, record, now=now)
