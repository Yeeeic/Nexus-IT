"""Protect global users with role-specific RLS visibility.

Revision ID: 20260824_0010
Revises: 20260824_0009
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260824_0010"
down_revision: str | None = "20260824_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.users FORCE ROW LEVEL SECURITY;

        CREATE POLICY users_auth_select
            ON public.users
            FOR SELECT TO nexus_auth_user
            USING (true);

        CREATE POLICY users_auth_update
            ON public.users
            FOR UPDATE TO nexus_auth_user
            USING (true)
            WITH CHECK (true);

        CREATE POLICY users_tenant_select
            ON public.users
            FOR SELECT TO nexus_app_user
            USING (
                EXISTS (
                    SELECT 1
                    FROM public.organization_memberships AS membership
                    WHERE membership.user_id = users.id
                      AND membership.organization_id = public.current_organization_id()
                      AND membership.is_active
                )
            );

        GRANT SELECT (id, email, full_name, is_active, created_at)
            ON TABLE public.users TO nexus_app_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        REVOKE SELECT (id, email, full_name, is_active, created_at)
            ON TABLE public.users FROM nexus_app_user;
        DROP POLICY users_tenant_select ON public.users;
        DROP POLICY users_auth_update ON public.users;
        DROP POLICY users_auth_select ON public.users;
        ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.users DISABLE ROW LEVEL SECURITY;
        """
    )
    op.execute("RESET ROLE")
