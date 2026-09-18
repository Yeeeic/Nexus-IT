"""Allow opaque-token session lookup before user context is known.

Revision ID: 20260824_0008
Revises: 20260824_0007
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260824_0008"
down_revision: str | None = "20260824_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        DROP POLICY sessions_authenticated_user_select
            ON public.user_sessions;
        CREATE POLICY sessions_authenticated_user_select
            ON public.user_sessions
            FOR SELECT TO nexus_auth_user
            USING (
                session_token_hash = public.current_session_token_hash()
            );
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        DROP POLICY sessions_authenticated_user_select
            ON public.user_sessions;
        CREATE POLICY sessions_authenticated_user_select
            ON public.user_sessions
            FOR SELECT TO nexus_auth_user
            USING (
                user_id = public.current_user_id()
                AND session_token_hash = public.current_session_token_hash()
            );
        """
    )
    op.execute("RESET ROLE")
