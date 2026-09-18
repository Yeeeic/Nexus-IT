"""Restore tenant isolation and minimum-privilege auth grants.

Revision ID: 20260825_0019
Revises: 20260825_0018
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260825_0019"
down_revision: str | None = "20260825_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        REVOKE SELECT ON TABLE public.organizations
            FROM nexus_auth_user, nexus_app_user, nexus_runtime;
        GRANT SELECT ON TABLE public.organizations TO nexus_app_user;
        GRANT SELECT (id, name, is_active)
            ON TABLE public.organizations TO nexus_auth_user;

        DROP POLICY IF EXISTS organizations_runtime_select
            ON public.organizations;

        REVOKE SELECT, UPDATE ON TABLE public.users FROM nexus_auth_user;
        GRANT SELECT (full_name) ON TABLE public.users TO nexus_auth_user;

        REVOKE SELECT, INSERT, UPDATE ON TABLE public.user_sessions
            FROM nexus_auth_user;

        DROP POLICY IF EXISTS sessions_authenticated_user_update
            ON public.user_sessions;
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
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        GRANT SELECT ON TABLE public.organizations
            TO nexus_auth_user, nexus_app_user, nexus_runtime;
        GRANT SELECT, UPDATE ON TABLE public.users TO nexus_auth_user;
        GRANT SELECT, INSERT, UPDATE ON TABLE public.user_sessions
            TO nexus_auth_user;

        CREATE POLICY organizations_runtime_select
            ON public.organizations
            FOR SELECT TO nexus_app_user, nexus_runtime
            USING (is_active);

        DROP POLICY IF EXISTS sessions_authenticated_user_update
            ON public.user_sessions;
        CREATE POLICY sessions_authenticated_user_update
            ON public.user_sessions
            FOR UPDATE TO nexus_auth_user
            USING (user_id = public.current_user_id())
            WITH CHECK (user_id = public.current_user_id());
        """
    )
    op.execute("RESET ROLE")
