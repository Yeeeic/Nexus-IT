"""Tenant-safe RBAC and audit administration contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RoleSummary:
    id: UUID
    name: str
    description: str
    is_system: bool
    permissions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuditLogSummary:
    id: UUID
    actor_id: UUID | None
    actor_type: Literal["USER", "AGENT", "SYSTEM"]
    action: str
    resource_type: str
    resource_id: UUID | None
    status: Literal["SUCCESS", "FAILURE", "DENIED"]
    details: dict[str, str]
    created_at: datetime


class AdministrationRejected(Exception):
    """Requested tenant administration resource is not valid or visible."""


class Administration(Protocol):
    async def list_roles(self, organization_id: UUID) -> tuple[RoleSummary, ...]: ...

    async def create_role(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        name: str,
        description: str,
        permissions: tuple[str, ...],
    ) -> RoleSummary: ...

    async def assign_role(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        role_id: UUID,
        user_id: UUID,
    ) -> None: ...

    async def list_audit_logs(
        self,
        *,
        organization_id: UUID,
        limit: int,
        before: datetime | None,
        action: str | None,
    ) -> tuple[AuditLogSummary, ...]: ...
