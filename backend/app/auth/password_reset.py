"""Opaque, single-use password-reset token primitives."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import secrets
from typing import Protocol
from uuid import UUID, uuid4

from backend.app.audit import AuditEvent
from backend.app.auth.passwords import hash_password


def hash_reset_secret(secret: str, pepper: bytes) -> bytes:
    """Hash reset secret with server-held pepper for safe persistence."""
    if len(pepper) < 32:
        raise ValueError("password reset pepper must contain at least 32 bytes")
    return hmac.new(pepper, secret.encode("ascii"), hashlib.sha256).digest()


def parse_reset_token(value: str) -> tuple[UUID, str]:
    """Parse public identifier and secret without accepting ambiguous forms."""
    try:
        token_id_value, secret = value.split(".", maxsplit=1)
        token_id = UUID(token_id_value)
    except (AttributeError, ValueError):
        raise ValueError("invalid password reset token") from None
    if not secret or "." in secret:
        raise ValueError("invalid password reset token")
    return token_id, secret


@dataclass(frozen=True, slots=True)
class PasswordResetToken:
    token_id: UUID
    value: str
    secret_hash: bytes

    @classmethod
    def generate(cls, pepper: bytes) -> "PasswordResetToken":
        token_id = uuid4()
        secret = secrets.token_urlsafe(32)
        return cls(
            token_id=token_id,
            value=f"{token_id}.{secret}",
            secret_hash=hash_reset_secret(secret, pepper),
        )

    def __repr__(self) -> str:
        return f"PasswordResetToken(token_id={self.token_id!r}, value=Secret('**********'))"


@dataclass(frozen=True, slots=True)
class PasswordResetRecord:
    token_id: UUID
    user_id: UUID
    secret_hash: bytes
    expires_at: datetime
    used_at: datetime | None
    is_revoked: bool


class PasswordResetRejected(Exception):
    def __init__(self) -> None:
        super().__init__("Solicitud de restablecimiento invÃ¡lida o expirada")


class PasswordResetUnavailable(Exception):
    def __init__(self) -> None:
        super().__init__("Servicio de restablecimiento no disponible")


class PasswordResetRepository(Protocol):
    async def lock_password_reset_token(
        self, token_id: UUID
    ) -> PasswordResetRecord | None: ...

    async def consume_password_reset(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        password_hash: str,
        used_at: datetime,
    ) -> None: ...

    async def append_audit(self, event: AuditEvent) -> None: ...


RepositoryFactory = Callable[
    [], AbstractAsyncContextManager[PasswordResetRepository]
]


class PasswordResetRequestGuard(Protocol):
    async def preflight(self, account: str, ip_address: str) -> object: ...


class PasswordResetApplication:
    """Validate and consume a reset token in one database transaction."""

    def __init__(
        self,
        repository_factory: RepositoryFactory,
        *,
        pepper: bytes,
        request_guard: PasswordResetRequestGuard,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if len(pepper) < 32:
            raise ValueError("password reset pepper must contain at least 32 bytes")
        self._repository_factory = repository_factory
        self._pepper = pepper
        self._request_guard = request_guard
        self._clock = clock
        self._id_factory = id_factory

    async def consume(
        self,
        token_value: str,
        new_password: str,
        *,
        ip_address: str,
        user_agent: str | None = None,
    ) -> None:
        await self._request_guard.preflight("password-reset", ip_address)
        # Expensive hashing occurs for every request and before locking a row.
        replacement_hash = hash_password(new_password)
        try:
            token_id, secret = parse_reset_token(token_value)
            token_was_parsed = True
        except ValueError:
            token_id, secret = UUID(int=0), "invalid"
            token_was_parsed = False
        presented_hash = hash_reset_secret(secret, self._pepper)
        now = self._clock()

        try:
            async with self._repository_factory() as repository:
                record = await repository.lock_password_reset_token(token_id)
                stored_hash = record.secret_hash if record else bytes(32)
                secret_matches = hmac.compare_digest(
                    stored_hash,
                    presented_hash,
                )
                valid = bool(
                    token_was_parsed
                    and record is not None
                    and record.used_at is None
                    and not record.is_revoked
                    and record.expires_at > now
                    and secret_matches
                )
                if not valid or record is None:
                    raise PasswordResetRejected
                await repository.consume_password_reset(
                    token_id=record.token_id,
                    user_id=record.user_id,
                    password_hash=replacement_hash,
                    used_at=now,
                )
                await repository.append_audit(
                    AuditEvent(
                        id=self._id_factory(),
                        organization_id=None,
                        actor_id=record.user_id,
                        actor_type="USER",
                        ip_address=ip_address,
                        user_agent=(user_agent or "").strip()[:255] or None,
                        action="AUTH.PASSWORD_RESET_SUCCESS",
                        resource_type="USER",
                        resource_id=record.user_id,
                        status="SUCCESS",
                        details={},
                    )
                )
        except PasswordResetRejected:
            raise
        except Exception:
            raise PasswordResetUnavailable from None
