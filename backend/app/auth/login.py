"""Tenant-safe login coordination without HTTP or database coupling."""

from collections.abc import Callable
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import ipaddress
from typing import Protocol
from uuid import UUID

from backend.app.auth.cookies import SESSION_IDLE_SECONDS
from backend.app.auth.schemas import LoginRequest
from backend.app.auth.service import (
    CredentialRecord,
    AuthenticationRejected,
    AuthenticationService,
    authenticate_credential,
)
from backend.app.auth.session_tokens import (
    SessionSecrets,
    hash_token,
    issue_session_secrets,
)


class LoginStatus(StrEnum):
    AUTHENTICATED = "AUTHENTICATED"
    ORGANIZATION_SELECTION_REQUIRED = "ORGANIZATION_SELECTION_REQUIRED"


@dataclass(frozen=True, slots=True)
class ActiveMembership:
    organization_id: UUID
    organization_name: str


@dataclass(frozen=True, slots=True)
class SessionCreation:
    session_id: UUID
    user_id: UUID
    organization_id: UUID | None
    session_token_hash: bytes
    csrf_token_hash: bytes
    expires_at: datetime
    last_seen_at: datetime
    user_agent: str | None
    ip_address: str | None


@dataclass(frozen=True, slots=True, repr=False)
class LoginResult:
    status: LoginStatus
    organizations: tuple[ActiveMembership, ...]
    secrets: SessionSecrets
    user_id: UUID | None = None
    organization_id: UUID | None = None

    def __repr__(self) -> str:
        return (
            f"LoginResult(status={self.status!r}, "
            f"organizations={self.organizations!r}, <redacted>)"
        )


class MembershipReader(Protocol):
    def list_active_for_user(
        self,
        user_id: UUID,
    ) -> tuple[ActiveMembership, ...]: ...


class SessionStore(Protocol):
    def replace_for_login(
        self,
        creation: SessionCreation,
        *,
        previous_token_hash: bytes | None,
    ) -> None: ...


class AsyncLoginRepository(Protocol):
    async def find_by_email(
        self,
        normalized_email: str,
    ) -> CredentialRecord | None: ...

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


def _bounded_user_agent(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()[:255]
    return normalized or None


def _validated_ip_address(value: str | None) -> str | None:
    if value is None:
        return None
    return str(ipaddress.ip_address(value))


def _prepare_login(
    *,
    user_id: UUID,
    memberships: tuple[ActiveMembership, ...],
    now: datetime,
    issue_secrets: Callable[[], SessionSecrets],
    previous_session_token: str | None,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[LoginResult, SessionCreation, bytes | None]:
    if not memberships:
        raise AuthenticationRejected

    organization_id = (
        memberships[0].organization_id if len(memberships) == 1 else None
    )
    status = (
        LoginStatus.AUTHENTICATED
        if organization_id is not None
        else LoginStatus.ORGANIZATION_SELECTION_REQUIRED
    )
    secrets = issue_secrets()
    creation = SessionCreation(
        session_id=secrets.session_id,
        user_id=user_id,
        organization_id=organization_id,
        session_token_hash=secrets.session_token_hash,
        csrf_token_hash=secrets.csrf_token_hash,
        expires_at=now + timedelta(seconds=SESSION_IDLE_SECONDS),
        last_seen_at=now,
        user_agent=_bounded_user_agent(user_agent),
        ip_address=_validated_ip_address(ip_address),
    )
    previous_token_hash = (
        hash_token(previous_session_token)
        if previous_session_token is not None
        else None
    )
    result = LoginResult(
        status=status,
        organizations=memberships if organization_id is None else (),
        secrets=secrets,
        user_id=user_id,
        organization_id=organization_id,
    )
    return result, creation, previous_token_hash


class LoginCoordinator:
    def __init__(
        self,
        *,
        authentication: AuthenticationService,
        membership_reader: MembershipReader,
        session_store: SessionStore,
        issue_secrets: Callable[[], SessionSecrets] = issue_session_secrets,
    ) -> None:
        self._authentication = authentication
        self._membership_reader = membership_reader
        self._session_store = session_store
        self._issue_secrets = issue_secrets

    def login(
        self,
        request: LoginRequest,
        *,
        now: datetime,
        previous_session_token: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> LoginResult:
        identity = self._authentication.authenticate(request, now=now)
        memberships = self._membership_reader.list_active_for_user(
            identity.user_id
        )
        result, creation, previous_token_hash = _prepare_login(
            user_id=identity.user_id,
            memberships=memberships,
            now=now,
            issue_secrets=self._issue_secrets,
            previous_session_token=previous_session_token,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self._session_store.replace_for_login(
            creation,
            previous_token_hash=previous_token_hash,
        )
        return result


class AsyncLoginCoordinator:
    """Async application flow backed by one external transaction boundary."""

    def __init__(
        self,
        *,
        repository: AsyncLoginRepository,
        issue_secrets: Callable[[], SessionSecrets] = issue_session_secrets,
    ) -> None:
        self._repository = repository
        self._issue_secrets = issue_secrets

    async def login(
        self,
        request: LoginRequest,
        *,
        now: datetime,
        previous_session_token: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        force_rejection: bool = False,
    ) -> LoginResult:
        record = await self._repository.find_by_email(request.email)
        identity = await asyncio.to_thread(
            authenticate_credential,
            request,
            record,
            now=now,
        )
        if force_rejection:
            raise AuthenticationRejected

        memberships = await self._repository.list_active_for_user(
            identity.user_id
        )
        result, creation, previous_token_hash = _prepare_login(
            user_id=identity.user_id,
            memberships=memberships,
            now=now,
            issue_secrets=self._issue_secrets,
            previous_session_token=previous_session_token,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await self._repository.replace_for_login(
            creation,
            previous_token_hash=previous_token_hash,
        )
        return result
