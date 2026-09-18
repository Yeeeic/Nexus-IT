"""Opaque session and CSRF token primitives."""

from dataclasses import dataclass
import hashlib
import hmac
import secrets
from uuid import UUID, uuid4


TOKEN_ENTROPY_BYTES = 32


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def verify_token(token: str, expected_hash: bytes) -> bool:
    return hmac.compare_digest(hash_token(token), expected_hash)


@dataclass(frozen=True, slots=True, repr=False)
class SessionSecrets:
    session_id: UUID
    session_token: str
    session_token_hash: bytes
    csrf_token: str
    csrf_token_hash: bytes

    def __repr__(self) -> str:
        return f"SessionSecrets(session_id={self.session_id!r}, <redacted>)"


def issue_session_secrets() -> SessionSecrets:
    session_token = secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)
    csrf_token = secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)
    return SessionSecrets(
        session_id=uuid4(),
        session_token=session_token,
        session_token_hash=hash_token(session_token),
        csrf_token=csrf_token,
        csrf_token_hash=hash_token(csrf_token),
    )
