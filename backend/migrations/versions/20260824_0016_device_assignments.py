"""Add scoped device assignments and explicit full-read permissions.

Revision ID: 20260824_0016
Revises: 20260824_0015
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0016"
down_revision: str | None = "20260824_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_SCOPE_ID = "00000000-0000-0000-0000-000000000000"
ADMIN_ID = "10000000-0000-4000-8000-000000000001"
TECHNICIAN_ID = "10000000-0000-4000-8000-000000000002"
PERMISSIONS = {
    "devices:read_all": "20000000-0000-4000-8000-000000000025",
    "devices:assign": "20000000-0000-4000-8000-000000000026",
    "metrics:read_all": "20000000-0000-4000-8000-000000000027",
    "inventory:read_all": "20000000-0000-4000-8000-000000000028",
}


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.create_table(
        "device_assignments",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["devices.organization_id", "devices.id"],
            name="fk_device_assignments_device",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            name="fk_device_assignments_user_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "assigned_by"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            name="fk_device_assignments_actor_membership",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "device_id",
            "user_id",
            name="pk_device_assignments",
        ),
    )
    op.execute(
        """
        ALTER TABLE public.device_assignments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.device_assignments FORCE ROW LEVEL SECURITY;
        CREATE POLICY device_assignments_tenant_all ON public.device_assignments
            FOR ALL TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());
        REVOKE ALL ON TABLE public.device_assignments FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON TABLE public.device_assignments
            TO nexus_app_user;
        """
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
    descriptions = {
        "devices:read_all": "Read every device in the active organization",
        "devices:assign": "Assign organization devices to users",
        "metrics:read_all": "Read telemetry for every organization device",
        "inventory:read_all": "Read inventory for every organization device",
    }
    op.bulk_insert(
        permissions,
        [
            {"id": permission_id, "name": name, "description": descriptions[name]}
            for name, permission_id in PERMISSIONS.items()
        ],
    )
    op.bulk_insert(
        role_permissions,
        [
            {
                "role_scope_id": SYSTEM_SCOPE_ID,
                "role_id": role_id,
                "permission_id": PERMISSIONS[permission_name],
            }
            for role_id in (ADMIN_ID, TECHNICIAN_ID)
            for permission_name in PERMISSIONS
        ],
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    permission_ids = tuple(PERMISSIONS.values())
    role_permissions = sa.table(
        "role_permissions",
        sa.column("permission_id", postgresql.UUID(as_uuid=True)),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
    )
    op.execute(
        role_permissions.delete().where(
            role_permissions.c.permission_id.in_(permission_ids)
        )
    )
    op.execute(permissions.delete().where(permissions.c.id.in_(permission_ids)))
    op.drop_table("device_assignments")
    op.execute("RESET ROLE")
