"""Restore exact auth column grants after removing table-wide privileges.

Revision ID: 20260825_0020
Revises: 20260825_0019
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260825_0020"
down_revision: str | None = "20260825_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        GRANT SELECT (
            id, email, password_hash, full_name, is_active,
            failed_login_attempts, locked_until
        ) ON TABLE public.users TO nexus_auth_user;
        GRANT UPDATE (password_hash, failed_login_attempts, locked_until)
            ON TABLE public.users TO nexus_auth_user;

        GRANT SELECT (
            id, organization_id, user_id, csrf_token_hash, expires_at,
            last_seen_at, is_revoked, user_agent, ip_address, created_at
        ) ON TABLE public.user_sessions TO nexus_auth_user;
        GRANT INSERT (
            id, organization_id, user_id, session_token_hash, csrf_token_hash,
            expires_at, last_seen_at, user_agent, ip_address, created_at
        ) ON TABLE public.user_sessions TO nexus_auth_user;
        GRANT UPDATE (expires_at, last_seen_at, is_revoked)
            ON TABLE public.user_sessions TO nexus_auth_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        REVOKE SELECT (
            id, email, password_hash, full_name, is_active,
            failed_login_attempts, locked_until
        ) ON TABLE public.users FROM nexus_auth_user;
        REVOKE UPDATE (password_hash, failed_login_attempts, locked_until)
            ON TABLE public.users FROM nexus_auth_user;

        REVOKE SELECT (
            id, organization_id, user_id, csrf_token_hash, expires_at,
            last_seen_at, is_revoked, user_agent, ip_address, created_at
        ) ON TABLE public.user_sessions FROM nexus_auth_user;
        REVOKE INSERT (
            id, organization_id, user_id, session_token_hash, csrf_token_hash,
            expires_at, last_seen_at, user_agent, ip_address, created_at
        ) ON TABLE public.user_sessions FROM nexus_auth_user;
        REVOKE UPDATE (expires_at, last_seen_at, is_revoked)
            ON TABLE public.user_sessions FROM nexus_auth_user;
        """
    )
    op.execute("RESET ROLE")
