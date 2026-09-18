"""Seed immutable system roles and canonical permissions.

Revision ID: 20260824_0004
Revises: 20260824_0003
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0004"
down_revision: str | None = "20260824_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_SCOPE_ID = "00000000-0000-0000-0000-000000000000"
ROLE_IDS = {
    "ADMIN": "10000000-0000-4000-8000-000000000001",
    "TECHNICIAN": "10000000-0000-4000-8000-000000000002",
    "READER": "10000000-0000-4000-8000-000000000003",
}
PERMISSIONS = (
    ("org:read_settings", "Read organization settings"),
    ("org:update_settings", "Update organization settings"),
    ("users:manage", "Manage organization users"),
    ("roles:manage_custom", "Manage custom organization roles"),
    ("devices:read", "Read authorized devices"),
    ("devices:enroll", "Enroll devices"),
    ("devices:delete", "Delete devices"),
    ("metrics:ingest_batch", "Ingest metrics for authenticated device"),
    ("metrics:read_telemetry", "Read authorized device telemetry"),
    ("metrics:retry_dlq", "Retry dead-letter metric batches"),
    ("metrics:export_dlq_diagnostics", "Export sanitized DLQ diagnostics"),
    ("metrics:decide_dlq", "Resolve exhausted DLQ batches"),
    ("inventory:read", "Read authorized device inventory"),
    ("inventory:write", "Write inventory for authenticated device"),
    ("alerts:read", "Read organization alerts"),
    ("alerts:manage_rules", "Manage organization alert rules"),
    ("tickets:read", "Read authorized tickets"),
    ("tickets:create", "Create tickets"),
    ("tickets:update_status", "Update authorized ticket status"),
    ("tickets:internal_notes", "Manage internal ticket notes"),
    ("actions:request_exec", "Request allowlisted remote actions"),
    ("actions:approve_admin", "Approve privileged remote actions"),
    ("actions:agent_poll_ack", "Poll and acknowledge own device actions"),
    ("audit:read_logs", "Read organization audit logs"),
)
ROLE_PERMISSION_NAMES = {
    "ADMIN": {
        name
        for name, _ in PERMISSIONS
        if name
        not in {
            "metrics:ingest_batch",
            "inventory:write",
            "actions:agent_poll_ack",
        }
    },
    "TECHNICIAN": {
        "org:read_settings",
        "devices:read",
        "devices:enroll",
        "metrics:read_telemetry",
        "inventory:read",
        "alerts:read",
        "tickets:read",
        "tickets:create",
        "tickets:update_status",
        "tickets:internal_notes",
        "actions:request_exec",
    },
    "READER": {
        "devices:read",
        "metrics:read_telemetry",
        "inventory:read",
        "tickets:read",
        "tickets:create",
        "tickets:update_status",
    },
}


def _permission_id(index: int) -> str:
    return f"20000000-0000-4000-8000-{index:012d}"


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    roles = sa.table(
        "roles",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("organization_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("is_system", sa.Boolean()),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_scope_id", postgresql.UUID(as_uuid=True)),
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
        sa.column("permission_id", postgresql.UUID(as_uuid=True)),
    )

    op.bulk_insert(
        roles,
        [
            {
                "id": role_id,
                "organization_id": None,
                "name": role_name,
                "description": f"Immutable {role_name.lower()} system role",
                "is_system": True,
            }
            for role_name, role_id in ROLE_IDS.items()
        ],
    )
    permission_rows = [
        {
            "id": _permission_id(index),
            "name": name,
            "description": description,
        }
        for index, (name, description) in enumerate(PERMISSIONS, start=1)
    ]
    op.bulk_insert(permissions, permission_rows)
    permission_ids = {row[0]: _permission_id(index) for index, row in enumerate(PERMISSIONS, 1)}
    op.bulk_insert(
        role_permissions,
        [
            {
                "role_scope_id": SYSTEM_SCOPE_ID,
                "role_id": ROLE_IDS[role_name],
                "permission_id": permission_ids[permission_name],
            }
            for role_name, permission_names in ROLE_PERMISSION_NAMES.items()
            for permission_name in sorted(permission_names)
        ],
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
    )
    roles = sa.table("roles", sa.column("id", postgresql.UUID(as_uuid=True)))
    permissions = sa.table(
        "permissions", sa.column("id", postgresql.UUID(as_uuid=True))
    )
    role_ids = tuple(ROLE_IDS.values())
    permission_ids = tuple(_permission_id(index) for index in range(1, 25))

    op.execute(role_permissions.delete().where(role_permissions.c.role_id.in_(role_ids)))
    op.execute(roles.delete().where(roles.c.id.in_(role_ids)))
    op.execute(permissions.delete().where(permissions.c.id.in_(permission_ids)))
    op.execute("RESET ROLE")
