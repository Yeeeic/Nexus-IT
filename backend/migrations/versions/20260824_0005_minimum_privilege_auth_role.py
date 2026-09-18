"""Add minimum-privilege access for global identity authentication.

Revision ID: 20260824_0005
Revises: 20260824_0004
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260824_0005"
down_revision: str | None = "20260824_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $roles$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'nexus_auth_user'
            ) THEN
                CREATE ROLE nexus_auth_user
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOBYPASSRLS;
            END IF;
            ALTER ROLE nexus_auth_user
                NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                NOINHERIT NOBYPASSRLS;
            EXECUTE format('GRANT nexus_auth_user TO %I', current_user);
        END
        $roles$;
        """
    )
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        CREATE FUNCTION public.current_user_id()
        RETURNS uuid
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RETURN NULLIF(current_setting('app.current_user_id', true), '')::uuid;
        EXCEPTION
            WHEN invalid_text_representation THEN
                RETURN NULL;
        END;
        $function$;

        REVOKE ALL ON FUNCTION public.current_user_id() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.current_user_id() TO nexus_auth_user;

        CREATE POLICY memberships_authenticated_user_select
            ON public.organization_memberships
            FOR SELECT TO nexus_auth_user
            USING (
                user_id = public.current_user_id()
                AND is_active
            );

        CREATE POLICY organizations_authenticated_user_select
            ON public.organizations
            FOR SELECT TO nexus_auth_user
            USING (
                is_active
                AND EXISTS (
                    SELECT 1
                    FROM public.organization_memberships AS membership
                    WHERE membership.organization_id = organizations.id
                      AND membership.user_id = public.current_user_id()
                      AND membership.is_active
                )
            );

        GRANT USAGE ON SCHEMA public TO nexus_auth_user;
        GRANT SELECT (id, email, password_hash, is_active,
                      failed_login_attempts, locked_until)
            ON TABLE public.users TO nexus_auth_user;
        GRANT UPDATE (failed_login_attempts, locked_until)
            ON TABLE public.users TO nexus_auth_user;
        GRANT SELECT ON TABLE public.organization_memberships TO nexus_auth_user;
        GRANT SELECT (id, name) ON TABLE public.organizations TO nexus_auth_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        DROP POLICY organizations_authenticated_user_select
            ON public.organizations;
        DROP POLICY memberships_authenticated_user_select
            ON public.organization_memberships;
        REVOKE SELECT (id, name)
            ON TABLE public.organizations FROM nexus_auth_user;
        REVOKE SELECT ON TABLE public.organization_memberships
            FROM nexus_auth_user;
        REVOKE UPDATE (failed_login_attempts, locked_until)
            ON TABLE public.users FROM nexus_auth_user;
        REVOKE SELECT (id, email, password_hash, is_active,
                       failed_login_attempts, locked_until)
            ON TABLE public.users FROM nexus_auth_user;
        REVOKE EXECUTE ON FUNCTION public.current_user_id()
            FROM nexus_auth_user;
        DROP FUNCTION public.current_user_id();
        REVOKE ALL ON SCHEMA public FROM nexus_auth_user;
        """
    )
    op.execute("RESET ROLE")
    # Retain database-wide role. It may predate this schema and now has no access.
