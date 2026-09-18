"""Internal append-only audit event contract."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID


AuditActorType = Literal["USER", "AGENT", "SYSTEM"]
AuditStatus = Literal["SUCCESS", "FAILURE", "DENIED"]


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: UUID
    organization_id: UUID | None
    actor_id: UUID | None
    actor_type: AuditActorType
    ip_address: str | None
    user_agent: str | None
    action: str
    resource_type: str
    resource_id: UUID | None
    status: AuditStatus
    details: dict[str, str] = field(default_factory=dict)
