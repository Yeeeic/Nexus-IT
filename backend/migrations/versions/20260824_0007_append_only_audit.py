"""Add partitioned append-only audit storage.

Revision ID: 20260824_0007
Revises: 20260824_0006
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0007"
down_revision: str | None = "20260824_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GLOBAL_SCOPE_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.execute(
        """
        DO $roles$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'nexus_audit_admin'
            ) THEN
                CREATE ROLE nexus_audit_admin
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOBYPASSRLS;
            END IF;
            ALTER ROLE nexus_audit_admin
                NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                NOINHERIT NOBYPASSRLS;
            EXECUTE format('GRANT nexus_audit_admin TO %I', current_user);
        END
        $roles$;
        """
    )
    op.execute("SET LOCAL ROLE nexus_admin")
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "scope_id",
            postgresql.UUID(as_uuid=True),
            sa.Computed(
                "COALESCE(organization_id, "
                f"'{_GLOBAL_SCOPE_ID}'::uuid)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('USER', 'AGENT', 'SYSTEM')",
            name="ck_audit_logs_actor_type",
        ),
        sa.CheckConstraint(
            "status IN ('SUCCESS', 'FAILURE', 'DENIED')",
            name="ck_audit_logs_status",
        ),
        sa.CheckConstraint(
            "length(btrim(action)) BETWEEN 1 AND 100",
            name="ck_audit_logs_action_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(resource_type)) BETWEEN 1 AND 80",
            name="ck_audit_logs_resource_type_not_blank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object' AND pg_column_size(details) <= 8192",
            name="ck_audit_logs_details_bounded_object",
        ),
        sa.CheckConstraint(
            "organization_id IS NOT NULL OR action LIKE 'AUTH.%'",
            name="ck_audit_logs_global_auth_only",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_audit_logs_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "scope_id",
            "id",
            "created_at",
            name="pk_audit_logs",
        ),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.execute(
        """
        CREATE TABLE public.audit_logs_2026
            PARTITION OF public.audit_logs
            FOR VALUES FROM ('2026-01-01 00:00:00+00')
                         TO ('2027-01-01 00:00:00+00');
        CREATE TABLE public.audit_logs_2027
            PARTITION OF public.audit_logs
            FOR VALUES FROM ('2027-01-01 00:00:00+00')
                         TO ('2028-01-01 00:00:00+00');
        CREATE TABLE public.audit_logs_default
            PARTITION OF public.audit_logs DEFAULT;

        CREATE INDEX ix_audit_logs_organization_created_at
            ON public.audit_logs (organization_id, created_at DESC);
        CREATE INDEX ix_audit_logs_action_created_at
            ON public.audit_logs (action, created_at DESC);

        ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.audit_logs FORCE ROW LEVEL SECURITY;

        CREATE POLICY audit_logs_tenant_select
            ON public.audit_logs
            FOR SELECT TO nexus_app_user
            USING (organization_id = public.current_organization_id());

        CREATE POLICY audit_logs_tenant_insert
            ON public.audit_logs
            FOR INSERT TO nexus_app_user
            WITH CHECK (organization_id = public.current_organization_id());

        CREATE POLICY audit_logs_auth_insert
            ON public.audit_logs
            FOR INSERT TO nexus_auth_user
            WITH CHECK (
                (
                    organization_id IS NULL
                    AND action IN (
                        'AUTH.LOGIN_SUCCESS',
                        'AUTH.LOGIN_FAILURE',
                        'AUTH.LOGIN_BLOCKED'
                    )
                )
                OR EXISTS (
                    SELECT 1
                    FROM public.organization_memberships AS membership
                    WHERE membership.organization_id = audit_logs.organization_id
                      AND membership.user_id = public.current_user_id()
                      AND membership.is_active
                )
            );

        CREATE POLICY audit_logs_maintenance
            ON public.audit_logs
            FOR ALL TO nexus_audit_admin
            USING (true)
            WITH CHECK (true);

        REVOKE ALL ON TABLE public.audit_logs FROM PUBLIC;
        GRANT SELECT ON TABLE public.audit_logs TO nexus_app_user;
        GRANT INSERT (
            id, organization_id, actor_id, actor_type, ip_address, user_agent,
            action, resource_type, resource_id, status, details
        ) ON TABLE public.audit_logs TO nexus_app_user;
        REVOKE UPDATE, DELETE ON TABLE public.audit_logs FROM nexus_app_user;
        GRANT INSERT (
            id, organization_id, actor_id, actor_type, ip_address, user_agent,
            action, resource_type, resource_id, status, details
        ) ON TABLE public.audit_logs TO nexus_auth_user;
        GRANT SELECT, DELETE ON TABLE public.audit_logs TO nexus_audit_admin;
        REVOKE UPDATE, INSERT ON TABLE public.audit_logs FROM nexus_audit_admin;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.drop_table("audit_logs")
    op.execute("RESET ROLE")
    # Retain the database-wide maintenance role without object privileges.
