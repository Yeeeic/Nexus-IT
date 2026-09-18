"""Add tenant-safe relational RBAC tables.

Revision ID: 20260824_0003
Revises: 20260824_0002
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0003"
down_revision: str | None = "20260824_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_SCOPE_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.create_check_constraint(
        "ck_organizations_id_not_system_scope",
        "organizations",
        f"id <> '{SYSTEM_SCOPE_ID}'::uuid",
    )

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "scope_id",
            postgresql.UUID(as_uuid=True),
            sa.Computed(
                f"COALESCE(organization_id, '{SYSTEM_SCOPE_ID}'::uuid)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "(organization_id IS NULL) = is_system",
            name="ck_roles_system_scope",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 50",
            name="ck_roles_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(description)) BETWEEN 1 AND 255",
            name="ck_roles_description_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_roles_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("scope_id", "id", name="uq_roles_scope_id"),
    )
    op.create_index(
        "uq_roles_system_name",
        "roles",
        ["name"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "uq_roles_custom_organization_name",
        "roles",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.CheckConstraint(
            "name ~ '^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$'",
            name="ck_permissions_name_format",
        ),
        sa.CheckConstraint(
            "length(btrim(description)) BETWEEN 1 AND 255",
            name="ck_permissions_description_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("name", name="uq_permissions_name"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_scope_id", "role_id"],
            ["roles.scope_id", "roles.id"],
            name="fk_role_permissions_role_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name="fk_role_permissions_permission",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "role_scope_id",
            "role_id",
            "permission_id",
            name="pk_role_permissions",
        ),
    )

    op.create_table(
        "user_roles",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "role_scope_id = organization_id "
            f"OR role_scope_id = '{SYSTEM_SCOPE_ID}'::uuid",
            name="ck_user_roles_allowed_scope",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            name="fk_user_roles_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_scope_id", "role_id"],
            ["roles.scope_id", "roles.id"],
            name="fk_user_roles_role_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "user_id", "role_id", name="pk_user_roles"
        ),
    )
    op.create_index("ix_memberships_user_id", "organization_memberships", ["user_id"])
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])

    op.execute(
        f"""
        ALTER TABLE public.roles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.roles FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.role_permissions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.role_permissions FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.user_roles FORCE ROW LEVEL SECURITY;

        CREATE POLICY roles_tenant_select ON public.roles
            FOR SELECT TO nexus_app_user
            USING (
                organization_id IS NULL
                OR organization_id = public.current_organization_id()
            );
        CREATE POLICY roles_admin_all ON public.roles
            FOR ALL TO nexus_admin
            USING (true)
            WITH CHECK (true);
        CREATE POLICY role_permissions_tenant_select ON public.role_permissions
            FOR SELECT TO nexus_app_user
            USING (
                role_scope_id = '{SYSTEM_SCOPE_ID}'::uuid
                OR role_scope_id = public.current_organization_id()
            );
        CREATE POLICY role_permissions_admin_all ON public.role_permissions
            FOR ALL TO nexus_admin
            USING (true)
            WITH CHECK (true);
        CREATE POLICY user_roles_tenant_select ON public.user_roles
            FOR SELECT TO nexus_app_user
            USING (organization_id = public.current_organization_id());
        CREATE POLICY user_roles_admin_all ON public.user_roles
            FOR ALL TO nexus_admin
            USING (true)
            WITH CHECK (true);

        REVOKE ALL ON TABLE public.roles FROM PUBLIC;
        REVOKE ALL ON TABLE public.permissions FROM PUBLIC;
        REVOKE ALL ON TABLE public.role_permissions FROM PUBLIC;
        REVOKE ALL ON TABLE public.user_roles FROM PUBLIC;
        GRANT SELECT ON TABLE public.roles TO nexus_app_user;
        GRANT SELECT ON TABLE public.permissions TO nexus_app_user;
        GRANT SELECT ON TABLE public.role_permissions TO nexus_app_user;
        GRANT SELECT ON TABLE public.user_roles TO nexus_app_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.drop_index("ix_memberships_user_id", table_name="organization_memberships")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_constraint(
        "ck_organizations_id_not_system_scope",
        "organizations",
        type_="check",
    )
    op.execute("RESET ROLE")
