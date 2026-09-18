"""Create the hardened multi-tenant foundation.

Revision ID: 20260824_0001
Revises: None
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $roles$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_admin') THEN
                CREATE ROLE nexus_admin
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_app_user') THEN
                CREATE ROLE nexus_app_user
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
            ALTER ROLE nexus_admin
                NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            ALTER ROLE nexus_app_user
                NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            EXECUTE format('GRANT nexus_admin TO %I', current_user);
        END
        $roles$;
        """
    )
    op.execute("GRANT USAGE, CREATE ON SCHEMA public TO nexus_admin")
    op.execute("SET LOCAL ROLE nexus_admin")

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "settings",
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
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_organizations_slug_normalized",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_organizations_name_not_blank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(settings) = 'object'",
            name="ck_organizations_settings_object",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )

    op.execute(
        """
        CREATE FUNCTION public.current_organization_id()
        RETURNS uuid
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RETURN NULLIF(current_setting('app.current_organization_id', true), '')::uuid;
        EXCEPTION
            WHEN invalid_text_representation THEN
                RETURN NULL;
        END;
        $function$;

        REVOKE ALL ON FUNCTION public.current_organization_id() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.current_organization_id() TO nexus_app_user;

        ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.organizations FORCE ROW LEVEL SECURITY;

        CREATE POLICY organizations_tenant_select
            ON public.organizations
            FOR SELECT
            TO nexus_app_user
            USING (id = public.current_organization_id());

        CREATE POLICY organizations_tenant_update
            ON public.organizations
            FOR UPDATE
            TO nexus_app_user
            USING (id = public.current_organization_id())
            WITH CHECK (id = public.current_organization_id());

        REVOKE ALL ON TABLE public.organizations FROM PUBLIC;
        GRANT USAGE ON SCHEMA public TO nexus_app_user;
        GRANT SELECT ON TABLE public.organizations TO nexus_app_user;
        GRANT UPDATE (name, settings) ON TABLE public.organizations TO nexus_app_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.drop_table("organizations")
    op.execute("DROP FUNCTION public.current_organization_id()")
    op.execute("RESET ROLE")
    op.execute("REVOKE ALL ON SCHEMA public FROM nexus_app_user")
    # Database-wide security principals are retained deliberately. Removing a
    # pre-existing shared role during a schema downgrade could break other users.
