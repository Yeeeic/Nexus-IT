"""Opaque session authentication, renewal, and CSRF verification."""

from dataclasses import dataclass
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from backend.app.auth.cookies import SESSION_IDLE_SECONDS
from backend.app.auth.session_tokens import hash_token, verify_token


SESSION_ABSOLUTE_LIFETIME = timedelta(days=7)


class SessionRejected(Exception):
    def __init__(self) -> None:
        super().__init__("Sesión inválida o expirada")


class CsrfRejected(Exception):
    def __init__(self) -> None:
        super().__init__("Protección CSRF inválida")


class SessionUnavailable(Exception):
    def __init__(self) -> None:
        super().__init__("Servicio de sesión no disponible")


class AuthorizationRejected(Exception):
    def __init__(self) -> None:
        super().__init__("Permiso insuficiente")


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: UUID
    organization_id: UUID | None
    user_id: UUID
    csrf_token_hash: bytes
    expires_at: datetime
    last_seen_at: datetime
    is_revoked: bool
    created_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class SessionIdentity:
    session_id: UUID
    organization_id: UUID | None
    user_id: UUID
    csrf_token_hash: bytes
    permissions: frozenset[str] = frozenset()

    def __repr__(self) -> str:
        return (
            f"SessionIdentity(session_id={self.session_id!r}, "
            f"organization_id={self.organization_id!r}, "
            f"user_id={self.user_id!r}, <redacted>)"
        )

    def verify_csrf(self, *, cookie: str | None, header: str | None) -> None:
        cookie_matches = verify_token(cookie or "", self.csrf_token_hash)
        header_matches = verify_token(header or "", self.csrf_token_hash)
        if not cookie_matches or not header_matches:
            raise CsrfRejected


from backend.app.auth.login import ActiveMembership
from backend.app.auth.schemas import LoginOrganization, UserMeResponse


class SessionRepository(Protocol):
    async def find_by_token_hash(
        self,
        token_hash: bytes,
    ) -> SessionRecord | None: ...

    async def touch_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        last_seen_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    async def load_permissions(
        self,
        *,
        user_id: UUID,
        organization_id: UUID,
    ) -> frozenset[str]: ...

    async def get_user_profile(
        self,
        user_id: UUID,
    ) -> tuple[str, str]: ...

    async def list_active_for_user(
        self,
        user_id: UUID,
    ) -> tuple[ActiveMembership, ...]: ...


class SessionAuthenticationService:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def authenticate(
        self,
        session_token: str,
        *,
        now: datetime,
        require_organization: bool,
    ) -> SessionIdentity:
        if not 1 <= len(session_token) <= 256:
            raise SessionRejected
        token_hash = hash_token(session_token)
        record = await self._repository.find_by_token_hash(token_hash)
        if record is None:
            raise SessionRejected

        absolute_expiry = record.created_at + SESSION_ABSOLUTE_LIFETIME
        idle_boundary = record.last_seen_at + timedelta(
            seconds=SESSION_IDLE_SECONDS
        )
        invalid = (
            record.is_revoked
            or record.expires_at <= now
            or idle_boundary <= now
            or absolute_expiry <= now
            or (require_organization and record.organization_id is None)
        )
        if invalid:
            raise SessionRejected

        renewed_expiry = min(
            now + timedelta(seconds=SESSION_IDLE_SECONDS),
            absolute_expiry,
        )
        await self._repository.touch_session(
            session_id=record.session_id,
            user_id=record.user_id,
            last_seen_at=now,
            expires_at=renewed_expiry,
        )
        return SessionIdentity(
            session_id=record.session_id,
            organization_id=record.organization_id,
            user_id=record.user_id,
            csrf_token_hash=record.csrf_token_hash,
        )


SessionRepositoryFactory = Callable[
    [], AbstractAsyncContextManager[SessionRepository]
]


class SessionApplicationService:
    def __init__(
        self,
        *,
        repository_factory: SessionRepositoryFactory,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository_factory = repository_factory
        self._clock = clock

    async def authenticate(
        self,
        session_token: str,
        *,
        require_organization: bool = True,
    ) -> SessionIdentity:
        try:
            async with self._repository_factory() as repository:
                identity = await SessionAuthenticationService(
                    repository
                ).authenticate(
                    session_token,
                    now=self._clock(),
                    require_organization=require_organization,
                )
                if identity.organization_id is None:
                    return identity
                permissions = await repository.load_permissions(
                    user_id=identity.user_id,
                    organization_id=identity.organization_id,
                )
                return SessionIdentity(
                    session_id=identity.session_id,
                    organization_id=identity.organization_id,
                    user_id=identity.user_id,
                    csrf_token_hash=identity.csrf_token_hash,
                    permissions=permissions,
                )
        except SessionRejected:
            raise
        except Exception:
            raise SessionUnavailable from None

    async def get_me(
        self,
        session_token: str,
    ) -> UserMeResponse:
        try:
            async with self._repository_factory() as repository:
                identity = await SessionAuthenticationService(
                    repository
                ).authenticate(
                    session_token,
                    now=self._clock(),
                    require_organization=False,
                )
                email, full_name = await repository.get_user_profile(identity.user_id)
                memberships = await repository.list_active_for_user(identity.user_id)
                available_orgs = tuple(
                    LoginOrganization(
                        id=membership.organization_id,
                        name=membership.organization_name,
                    )
                    for membership in memberships
                )
                permissions: tuple[str, ...] = ()
                if identity.organization_id is not None:
                    perms = await repository.load_permissions(
                        user_id=identity.user_id,
                        organization_id=identity.organization_id,
                    )
                    permissions = tuple(sorted(perms))
                return UserMeResponse(
                    user_id=identity.user_id,
                    email=email,
                    full_name=full_name,
                    organization_id=identity.organization_id,
                    permissions=permissions,
                    available_organizations=available_orgs,
                )
        except SessionRejected:
            raise
        except Exception:
            raise SessionUnavailable from None
