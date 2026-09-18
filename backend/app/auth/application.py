"""Complete login application flow: limits, transaction, audit, and delay."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from backend.app.audit import AuditEvent, AuditStatus
from backend.app.auth.login import (
    AsyncLoginCoordinator,
    AsyncLoginRepository,
    LoginResult,
)
from backend.app.auth.rate_limit import (
    LoginRateLimiter,
    LoginRequestRateLimited,
)
from backend.app.auth.schemas import LoginRequest
from backend.app.auth.service import AuthenticationRejected


class LoginAuditRepository(AsyncLoginRepository, Protocol):
    async def append_audit(self, event: AuditEvent) -> None: ...

    async def record_credential_failure(
        self,
        normalized_email: str,
        *,
        now: datetime,
    ) -> None: ...

    async def clear_credential_failures(self, normalized_email: str) -> None: ...


RepositoryFactory = Callable[
    [], AbstractAsyncContextManager[LoginAuditRepository]
]


class LoginApplicationUnavailable(Exception):
    def __init__(self) -> None:
        super().__init__("Servicio de autenticación no disponible")


def _bounded_user_agent(value: str | None) -> str | None:
    if value is None:
        return None
    bounded = value.strip()[:255]
    return bounded or None


class LoginApplicationService:
    def __init__(
        self,
        *,
        repository_factory: RepositoryFactory,
        rate_limiter: LoginRateLimiter,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository_factory = repository_factory
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._sleeper = sleeper
        self._id_factory = id_factory

    def _audit_event(
        self,
        *,
        action: str,
        status: AuditStatus,
        ip_address: str,
        user_agent: str | None,
        actor_id: UUID | None = None,
        organization_id: UUID | None = None,
        details: dict[str, str] | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            id=self._id_factory(),
            organization_id=organization_id,
            actor_id=actor_id,
            actor_type="USER" if actor_id is not None else "SYSTEM",
            ip_address=ip_address,
            user_agent=_bounded_user_agent(user_agent),
            action=action,
            resource_type="USER",
            resource_id=actor_id,
            status=status,
            details=details or {},
        )

    async def _append_global_audit(
        self,
        event: AuditEvent,
        *,
        failed_email: str | None = None,
        now: datetime | None = None,
    ) -> None:
        try:
            async with self._repository_factory() as repository:
                if failed_email is not None and now is not None:
                    await repository.record_credential_failure(
                        failed_email,
                        now=now,
                    )
                await repository.append_audit(event)
        except Exception:
            raise LoginApplicationUnavailable from None

    async def login(
        self,
        request: LoginRequest,
        *,
        previous_session_token: str | None,
        user_agent: str | None,
        ip_address: str,
    ) -> LoginResult:
        try:
            preflight = await self._rate_limiter.preflight(
                request.email,
                ip_address,
            )
        except LoginRequestRateLimited:
            await self._append_global_audit(
                self._audit_event(
                    action="AUTH.LOGIN_BLOCKED",
                    status="DENIED",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details={"reason": "IP_RATE_LIMIT"},
                )
            )
            raise

        try:
            now = self._clock()
            async with self._repository_factory() as repository:
                result = await AsyncLoginCoordinator(
                    repository=repository
                ).login(
                    request,
                    now=now,
                    previous_session_token=previous_session_token,
                    user_agent=user_agent,
                    ip_address=ip_address,
                    force_rejection=preflight.credentials_blocked,
                )
                await repository.clear_credential_failures(request.email)
                await repository.append_audit(
                    self._audit_event(
                        action="AUTH.LOGIN_SUCCESS",
                        status="SUCCESS",
                        ip_address=ip_address,
                        user_agent=user_agent,
                        actor_id=result.user_id,
                        organization_id=result.organization_id,
                        details={"result": result.status.value},
                    )
                )
        except AuthenticationRejected:
            await self._append_global_audit(
                self._audit_event(
                    action=(
                        "AUTH.LOGIN_BLOCKED"
                        if preflight.credentials_blocked
                        else "AUTH.LOGIN_FAILURE"
                    ),
                    status="DENIED" if preflight.credentials_blocked else "FAILURE",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details={"reason": "INVALID_CREDENTIALS"},
                ),
                failed_email=request.email,
                now=now,
            )
            failure = await self._rate_limiter.record_failure(
                request.email,
                ip_address,
            )
            await self._sleeper(failure.delay_seconds)
            raise
        except LoginApplicationUnavailable:
            raise
        except Exception as err:
            raise LoginApplicationUnavailable from err

        try:
            await self._rate_limiter.record_success(request.email, ip_address)
        except Exception as err:
            raise LoginApplicationUnavailable from err
        return result
