"""Allow audited tenant RBAC administration.

Revision ID: 20260824_0015
Revises: 20260824_0014
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260824_0015"
down_revision: str | None = "20260824_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_SCOPE_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        f"""
        CREATE POLICY roles_tenant_insert ON public.roles
            FOR INSERT TO nexus_app_user
            WITH CHECK (
                organization_id = public.current_organization_id()
                AND NOT is_system
            );
        CREATE POLICY role_permissions_tenant_insert
            ON public.role_permissions
            FOR INSERT TO nexus_app_user
            WITH CHECK (role_scope_id = public.current_organization_id());
        CREATE POLICY user_roles_tenant_insert ON public.user_roles
            FOR INSERT TO nexus_app_user
            WITH CHECK (
                organization_id = public.current_organization_id()
                AND role_scope_id IN (
                    public.current_organization_id(),
                    '{SYSTEM_SCOPE_ID}'::uuid
                )
            );

        GRANT INSERT (id, organization_id, name, description, is_system)
            ON TABLE public.roles TO nexus_app_user;
        GRANT INSERT (role_scope_id, role_id, permission_id)
            ON TABLE public.role_permissions TO nexus_app_user;
        GRANT INSERT (organization_id, user_id, role_scope_id, role_id)
            ON TABLE public.user_roles TO nexus_app_user;

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
                        'AUTH.LOGOUT',
                        'AUTH.PASSWORD_RESET_REQUESTED',
                        'AUTH.PASSWORD_RESET_SUCCESS'
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

        REVOKE INSERT (organization_id, user_id, role_scope_id, role_id)
            ON TABLE public.user_roles FROM nexus_app_user;
        REVOKE INSERT (role_scope_id, role_id, permission_id)
            ON TABLE public.role_permissions FROM nexus_app_user;
        REVOKE INSERT (id, organization_id, name, description, is_system)
            ON TABLE public.roles FROM nexus_app_user;
        DROP POLICY user_roles_tenant_insert ON public.user_roles;
        DROP POLICY role_permissions_tenant_insert ON public.role_permissions;
        DROP POLICY roles_tenant_insert ON public.roles;
        """
    )
    op.execute("RESET ROLE")
