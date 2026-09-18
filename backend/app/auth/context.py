"""Authorized organization context selection with mandatory session rotation."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
import ipaddress
from typing import Protocol
from uuid import UUID, uuid4

from backend.app.audit import AuditEvent
from backend.app.auth.cookies import SESSION_IDLE_SECONDS
from backend.app.auth.login import (
    ActiveMembership,
    SessionCreation,
)
from backend.app.auth.session import (
    CsrfRejected,
    SessionAuthenticationService,
    SessionRejected,
    SessionRepository,
    SessionUnavailable,
)
from backend.app.auth.session_tokens import (
    SessionSecrets,
    hash_token,
    issue_session_secrets,
)


class ContextSelectionRejected(Exception):
    def __init__(self) -> None:
        super().__init__("Contexto de organización no autorizado")


class ContextRepository(SessionRepository, Protocol):
    async def list_active_for_user(
        self,
        user_id: UUID,
    ) -> tuple[ActiveMembership, ...]: ...

    async def replace_for_login(
        self,
        creation: SessionCreation,
        *,
        previous_token_hash: bytes | None,
    ) -> None: ...

    async def append_audit(self, event: AuditEvent) -> None: ...


@dataclass(frozen=True, slots=True, repr=False)
class ContextSelectionResult:
    organization_id: UUID
    secrets: SessionSecrets

    def __repr__(self) -> str:
        return (
            "ContextSelectionResult("
            f"organization_id={self.organization_id!r}, <redacted>)"
        )


class ContextSelectionService:
    def __init__(
        self,
        *,
        repository: ContextRepository,
        issue_secrets: Callable[[], SessionSecrets] = issue_session_secrets,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._issue_secrets = issue_secrets
        self._id_factory = id_factory

    async def select(
        self,
        *,
        session_token: str,
        csrf_cookie: str | None,
        csrf_header: str | None,
        organization_id: UUID,
        now: datetime,
        user_agent: str | None,
        ip_address: str,
    ) -> ContextSelectionResult:
        identity = await SessionAuthenticationService(
            self._repository
        ).authenticate(
            session_token,
            now=now,
            require_organization=False,
        )
        identity.verify_csrf(cookie=csrf_cookie, header=csrf_header)
        memberships = await self._repository.list_active_for_user(
            identity.user_id
        )
        if organization_id not in {
            membership.organization_id for membership in memberships
        }:
            raise ContextSelectionRejected

        secrets = self._issue_secrets()
        bounded_user_agent = (
            (user_agent.strip()[:255] or None)
            if user_agent is not None
            else None
        )
        normalized_ip = str(ipaddress.ip_address(ip_address))
        creation = SessionCreation(
            session_id=secrets.session_id,
            user_id=identity.user_id,
            organization_id=organization_id,
            session_token_hash=secrets.session_token_hash,
            csrf_token_hash=secrets.csrf_token_hash,
            expires_at=now + timedelta(seconds=SESSION_IDLE_SECONDS),
            last_seen_at=now,
            user_agent=bounded_user_agent,
            ip_address=normalized_ip,
        )
        await self._repository.replace_for_login(
            creation,
            previous_token_hash=hash_token(session_token),
        )
        await self._repository.append_audit(
            AuditEvent(
                id=self._id_factory(),
                organization_id=organization_id,
                actor_id=identity.user_id,
                actor_type="USER",
                ip_address=normalized_ip,
                user_agent=bounded_user_agent,
                action="AUTH.CONTEXT_SELECTED",
                resource_type="ORGANIZATION",
                resource_id=organization_id,
                status="SUCCESS",
                details={"result": "CONTEXT_SELECTED"},
            )
        )
        return ContextSelectionResult(
            organization_id=organization_id,
            secrets=secrets,
        )


ContextRepositoryFactory = Callable[
    [], AbstractAsyncContextManager[ContextRepository]
]


class ContextSelectionApplication:
    def __init__(
        self,
        *,
        repository_factory: ContextRepositoryFactory,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository_factory = repository_factory
        self._clock = clock

    async def select(
        self,
        *,
        session_token: str,
        csrf_cookie: str | None,
        csrf_header: str | None,
        organization_id: UUID,
        user_agent: str | None,
        ip_address: str,
    ) -> ContextSelectionResult:
        try:
            async with self._repository_factory() as repository:
                return await ContextSelectionService(
                    repository=repository
                ).select(
                    session_token=session_token,
                    csrf_cookie=csrf_cookie,
                    csrf_header=csrf_header,
                    organization_id=organization_id,
                    now=self._clock(),
                    user_agent=user_agent,
                    ip_address=ip_address,
                )
        except (ContextSelectionRejected, CsrfRejected, SessionRejected):
            raise
        except Exception:
            raise SessionUnavailable from None
