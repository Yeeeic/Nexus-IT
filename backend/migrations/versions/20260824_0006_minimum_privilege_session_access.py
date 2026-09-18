"""Add minimum-privilege authentication session access.

Revision ID: 20260824_0006
Revises: 20260824_0005
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260824_0006"
down_revision: str | None = "20260824_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        CREATE FUNCTION public.current_session_token_hash()
        RETURNS bytea
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog, public
        AS $function$
            SELECT CASE
                WHEN token_hash ~ '^[0-9a-fA-F]{64}$'
                    THEN decode(token_hash, 'hex')
                ELSE NULL
            END
            FROM (
                SELECT NULLIF(
                    current_setting('app.current_session_token_hash', true),
                    ''
                ) AS token_hash
            ) AS context;
        $function$;

        REVOKE ALL ON FUNCTION public.current_session_token_hash() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.current_session_token_hash()
            TO nexus_auth_user;

        CREATE POLICY sessions_authenticated_user_select
            ON public.user_sessions
            FOR SELECT TO nexus_auth_user
            USING (
                user_id = public.current_user_id()
                AND session_token_hash = public.current_session_token_hash()
            );

        CREATE POLICY sessions_authenticated_user_insert
            ON public.user_sessions
            FOR INSERT TO nexus_auth_user
            WITH CHECK (
                user_id = public.current_user_id()
                AND (
                    organization_id IS NULL
                    OR EXISTS (
                        SELECT 1
                        FROM public.organization_memberships AS membership
                        WHERE membership.organization_id = user_sessions.organization_id
                          AND membership.user_id = public.current_user_id()
                          AND membership.is_active
                    )
                )
            );

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

        GRANT SELECT (
            id, organization_id, user_id, csrf_token_hash, expires_at,
            last_seen_at, is_revoked, user_agent, ip_address, created_at
        ) ON TABLE public.user_sessions TO nexus_auth_user;
        GRANT INSERT (
            id, organization_id, user_id, session_token_hash, csrf_token_hash,
            expires_at, last_seen_at, user_agent, ip_address
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
        REVOKE UPDATE (expires_at, last_seen_at, is_revoked)
            ON TABLE public.user_sessions FROM nexus_auth_user;
        REVOKE INSERT (
            id, organization_id, user_id, session_token_hash, csrf_token_hash,
            expires_at, last_seen_at, user_agent, ip_address
        ) ON TABLE public.user_sessions FROM nexus_auth_user;
        REVOKE SELECT (
            id, organization_id, user_id, csrf_token_hash, expires_at,
            last_seen_at, is_revoked, user_agent, ip_address, created_at
        ) ON TABLE public.user_sessions FROM nexus_auth_user;

        DROP POLICY sessions_authenticated_user_update
            ON public.user_sessions;
        DROP POLICY sessions_authenticated_user_insert
            ON public.user_sessions;
        DROP POLICY sessions_authenticated_user_select
            ON public.user_sessions;

        REVOKE EXECUTE ON FUNCTION public.current_session_token_hash()
            FROM nexus_auth_user;
        DROP FUNCTION public.current_session_token_hash();
        """
    )
    op.execute("RESET ROLE")
