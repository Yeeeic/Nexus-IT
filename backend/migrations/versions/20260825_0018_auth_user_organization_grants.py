"""Grant is_active column on organizations to nexus_auth_user.

Revision ID: 20260825_0018
Revises: 20260824_0017
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260825_0018"
down_revision: str | None = "20260824_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $roles$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_runtime') THEN
                CREATE ROLE nexus_runtime
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
        END
        $roles$;
        """
    )
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        GRANT SELECT ON TABLE public.organizations TO nexus_auth_user, nexus_app_user, nexus_runtime;
        GRANT SELECT, UPDATE ON TABLE public.users TO nexus_auth_user;
        GRANT SELECT ON TABLE public.organization_memberships TO nexus_auth_user;

        GRANT INSERT (
            id, organization_id, user_id, session_token_hash, csrf_token_hash,
            expires_at, last_seen_at, created_at, user_agent, ip_address
        ) ON TABLE public.user_sessions TO nexus_auth_user;
        GRANT SELECT, INSERT, UPDATE ON TABLE public.user_sessions TO nexus_auth_user;

        DROP POLICY IF EXISTS organizations_runtime_select ON public.organizations;
        CREATE POLICY organizations_runtime_select
            ON public.organizations
            FOR SELECT TO nexus_app_user, nexus_runtime
            USING (is_active);

        DROP POLICY IF EXISTS sessions_authenticated_user_update ON public.user_sessions;
        CREATE POLICY sessions_authenticated_user_update
            ON public.user_sessions
            FOR UPDATE TO nexus_auth_user
            USING (
                user_id = public.current_user_id()
            )
            WITH CHECK (
                user_id = public.current_user_id()
            );
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        DROP POLICY IF EXISTS sessions_authenticated_user_update ON public.user_sessions;
        CREATE POLICY sessions_authenticated_user_update
            ON public.user_sessions
            FOR UPDATE TO nexus_auth_user
            USING (
                user_id = public.current_user_id()
                AND session_token_hash = public.current_session_token_hash()
            )
            WITH CHECK (
                user_id = public.current_user_id()
                AND session_token_hash = public.current_session_token_hash()
            );

        REVOKE INSERT (created_at)
            ON TABLE public.user_sessions FROM nexus_auth_user;

        REVOKE SELECT (is_active)
            ON TABLE public.organizations FROM nexus_auth_user;
        """
    )
    op.execute("RESET ROLE")
