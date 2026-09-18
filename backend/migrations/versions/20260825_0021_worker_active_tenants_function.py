"""Create list_active_tenant_ids SECURITY DEFINER function for worker organization scanning.

Revision ID: 20260825_0021
Revises: 20260825_0020
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260825_0021"
down_revision: str | None = "20260825_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.list_active_tenant_ids();

        CREATE FUNCTION public.list_active_tenant_ids()
        RETURNS TABLE (id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
            SELECT id FROM public.organizations WHERE is_active = true ORDER BY created_at;
        $function$;

        REVOKE ALL ON FUNCTION public.list_active_tenant_ids() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.list_active_tenant_ids() TO nexus_app_user;

        GRANT DELETE ON TABLE public.tickets, public.ticket_comments TO nexus_app_user;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE DELETE ON TABLE public.tickets, public.ticket_comments FROM nexus_app_user;
        DROP FUNCTION IF EXISTS public.list_active_tenant_ids();
        """
    )
