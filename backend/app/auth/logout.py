"""CSRF-protected immediate session revocation."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
import ipaddress
from typing import Protocol
from uuid import UUID, uuid4

from backend.app.audit import AuditEvent
from backend.app.auth.session import (
    CsrfRejected,
    SessionAuthenticationService,
    SessionRejected,
    SessionRepository,
    SessionUnavailable,
)


class LogoutRepository(SessionRepository, Protocol):
    async def revoke_current_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> None: ...

    async def append_audit(self, event: AuditEvent) -> None: ...


class LogoutService:
    def __init__(
        self,
        *,
        repository: LogoutRepository,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory

    async def logout(
        self,
        *,
        session_token: str,
        csrf_cookie: str | None,
        csrf_header: str | None,
        now: datetime,
        user_agent: str | None,
        ip_address: str,
    ) -> None:
        identity = await SessionAuthenticationService(
            self._repository
        ).authenticate(
            session_token,
            now=now,
            require_organization=False,
        )
        identity.verify_csrf(cookie=csrf_cookie, header=csrf_header)
        await self._repository.revoke_current_session(
            session_id=identity.session_id,
            user_id=identity.user_id,
        )
        bounded_user_agent = (
            (user_agent.strip()[:255] or None)
            if user_agent is not None
            else None
        )
        normalized_ip = str(ipaddress.ip_address(ip_address))
        await self._repository.append_audit(
            AuditEvent(
                id=self._id_factory(),
                organization_id=identity.organization_id,
                actor_id=identity.user_id,
                actor_type="USER",
                ip_address=normalized_ip,
                user_agent=bounded_user_agent,
                action="AUTH.LOGOUT",
                resource_type="SESSION",
                resource_id=identity.session_id,
                status="SUCCESS",
                details={"result": "REVOKED"},
            )
        )


LogoutRepositoryFactory = Callable[
    [], AbstractAsyncContextManager[LogoutRepository]
]


class LogoutApplication:
    def __init__(
        self,
        *,
        repository_factory: LogoutRepositoryFactory,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository_factory = repository_factory
        self._clock = clock

    async def logout(
        self,
        *,
        session_token: str,
        csrf_cookie: str | None,
        csrf_header: str | None,
        user_agent: str | None,
        ip_address: str,
    ) -> None:
        try:
            async with self._repository_factory() as repository:
                await LogoutService(repository=repository).logout(
                    session_token=session_token,
                    csrf_cookie=csrf_cookie,
                    csrf_header=csrf_header,
                    now=self._clock(),
                    user_agent=user_agent,
                    ip_address=ip_address,
                )
        except (CsrfRejected, SessionRejected):
            raise
        except Exception:
            raise SessionUnavailable from None
