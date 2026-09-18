"""Tenant-safe user directory contracts."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserSummary:
    id: UUID
    email: str
    full_name: str
    is_active: bool


class UserDirectory(Protocol):
    async def list_users(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[UserSummary, ...], UUID | None]: ...

    async def create_user(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        email: str,
        full_name: str,
        password_hash: str,
        role_name: str,
    ) -> UserSummary: ...

    async def toggle_user_active(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        user_id: UUID,
        is_active: bool,
    ) -> UserSummary: ...

    async def revoke_user_sessions(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        user_id: UUID,
    ) -> int: ...

    async def delete_user(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        user_id: UUID,
    ) -> bool: ...
