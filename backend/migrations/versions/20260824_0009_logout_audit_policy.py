"""Allow global logout audit for pending sessions.

Revision ID: 20260824_0009
Revises: 20260824_0008
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260824_0009"
down_revision: str | None = "20260824_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        DROP POLICY audit_logs_auth_insert ON public.audit_logs;
        CREATE POLICY audit_logs_auth_insert
            ON public.audit_logs
            FOR INSERT TO nexus_auth_user
            WITH CHECK (
                (
                    organization_id IS NULL
                    AND action IN (
                        'AUTH.LOGIN_SUCCESS',
                        'AUTH.LOGIN_FAILURE',
                        'AUTH.LOGIN_BLOCKED',
                        'AUTH.LOGOUT'
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
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        DROP POLICY audit_logs_auth_insert ON public.audit_logs;
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
        """
    )
    op.execute("RESET ROLE")
