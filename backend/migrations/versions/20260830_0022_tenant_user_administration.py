"""Harden tenant user administration with narrow database functions.

Revision ID: 20260830_0022
Revises: 20260825_0021
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260830_0022"
down_revision: str | None = "20260825_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DROP POLICY users_tenant_select ON public.users;
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

        CREATE FUNCTION public.assert_tenant_user_manager(
            p_organization_id uuid,
            p_actor_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF p_organization_id IS DISTINCT FROM public.current_organization_id()
               OR NOT EXISTS (
                    SELECT 1
                    FROM public.organization_memberships AS membership
                    JOIN public.user_roles AS assignment
                      ON assignment.organization_id = membership.organization_id
                     AND assignment.user_id = membership.user_id
                    JOIN public.role_permissions AS role_permission
                      ON role_permission.role_scope_id = assignment.role_scope_id
                     AND role_permission.role_id = assignment.role_id
                    JOIN public.permissions AS permission
                      ON permission.id = role_permission.permission_id
                    JOIN public.users AS actor
                      ON actor.id = membership.user_id
                    WHERE membership.organization_id = p_organization_id
                      AND membership.user_id = p_actor_id
                      AND membership.is_active
                      AND actor.is_active
                      AND permission.name = 'users:manage'
               ) THEN
                RAISE EXCEPTION 'tenant user administration denied'
                    USING ERRCODE = '42501';
            END IF;
        END;
        $function$;

        CREATE FUNCTION public.list_tenant_users(
            p_organization_id uuid,
            p_actor_id uuid,
            p_after_id uuid,
            p_fetch_limit integer
        ) RETURNS TABLE (
            id uuid, email varchar, full_name varchar, is_active boolean
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            PERFORM public.assert_tenant_user_manager(p_organization_id, p_actor_id);
            IF p_fetch_limit < 1 OR p_fetch_limit > 101 THEN
                RAISE EXCEPTION 'invalid pagination limit' USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
            SELECT
                account.id,
                account.email,
                account.full_name,
                (account.is_active AND membership.is_active)
            FROM public.organization_memberships AS membership
            JOIN public.users AS account ON account.id = membership.user_id
            WHERE membership.organization_id = p_organization_id
              AND (p_after_id IS NULL OR account.id > p_after_id)
            ORDER BY account.id
            LIMIT p_fetch_limit;
        END;
        $function$;

        CREATE FUNCTION public.create_tenant_user_membership(
            p_organization_id uuid,
            p_actor_id uuid,
            p_new_user_id uuid,
            p_email varchar,
            p_password_hash varchar,
            p_full_name varchar,
            p_role_name varchar
        ) RETURNS TABLE (
            id uuid, email varchar, full_name varchar, is_active boolean
        )
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            target_user public.users%ROWTYPE;
            selected_role record;
        BEGIN
            PERFORM public.assert_tenant_user_manager(p_organization_id, p_actor_id);
            SELECT role.id, role.scope_id INTO selected_role
            FROM public.roles AS role
            WHERE role.name = upper(p_role_name)
              AND role.is_system
              AND role.organization_id IS NULL;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'invalid system role' USING ERRCODE = '22023';
            END IF;

            SELECT account.* INTO target_user
            FROM public.users AS account
            WHERE account.email = lower(btrim(p_email));
            IF NOT FOUND THEN
                INSERT INTO public.users (
                    id, email, password_hash, full_name, is_active
                ) VALUES (
                    p_new_user_id, lower(btrim(p_email)), p_password_hash,
                    btrim(p_full_name), true
                ) RETURNING * INTO target_user;
            END IF;

            INSERT INTO public.organization_memberships (
                organization_id, user_id, is_active
            ) VALUES (p_organization_id, target_user.id, true)
            ON CONFLICT (organization_id, user_id)
            DO UPDATE SET is_active = true;

            DELETE FROM public.user_roles AS assignment
            USING public.roles AS role
            WHERE assignment.organization_id = p_organization_id
              AND assignment.user_id = target_user.id
              AND role.scope_id = assignment.role_scope_id
              AND role.id = assignment.role_id
              AND role.is_system;
            INSERT INTO public.user_roles (
                organization_id, user_id, role_scope_id, role_id
            ) VALUES (
                p_organization_id, target_user.id,
                selected_role.scope_id, selected_role.id
            );

            RETURN QUERY SELECT
                target_user.id, target_user.email, target_user.full_name,
                target_user.is_active;
        END;
        $function$;

        CREATE FUNCTION public.set_tenant_user_membership_active(
            p_organization_id uuid,
            p_actor_id uuid,
            p_user_id uuid,
            p_is_active boolean
        ) RETURNS TABLE (
            id uuid, email varchar, full_name varchar, is_active boolean
        )
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE target_user public.users%ROWTYPE;
        BEGIN
            PERFORM public.assert_tenant_user_manager(p_organization_id, p_actor_id);
            UPDATE public.organization_memberships AS membership
            SET is_active = p_is_active
            WHERE membership.organization_id = p_organization_id
              AND membership.user_id = p_user_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'tenant membership not found' USING ERRCODE = 'P0002';
            END IF;
            SELECT account.* INTO STRICT target_user
            FROM public.users AS account WHERE account.id = p_user_id;
            RETURN QUERY SELECT
                target_user.id, target_user.email, target_user.full_name,
                (target_user.is_active AND p_is_active);
        END;
        $function$;

        CREATE FUNCTION public.revoke_tenant_user_sessions(
            p_organization_id uuid,
            p_actor_id uuid,
            p_user_id uuid
        ) RETURNS integer
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE affected integer;
        BEGIN
            PERFORM public.assert_tenant_user_manager(p_organization_id, p_actor_id);
            IF NOT EXISTS (
                SELECT 1 FROM public.organization_memberships AS membership
                WHERE membership.organization_id = p_organization_id
                  AND membership.user_id = p_user_id
            ) THEN
                RAISE EXCEPTION 'tenant membership not found' USING ERRCODE = 'P0002';
            END IF;
            UPDATE public.user_sessions AS session
            SET is_revoked = true
            WHERE session.organization_id = p_organization_id
              AND session.user_id = p_user_id
              AND NOT session.is_revoked;
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN affected;
        END;
        $function$;

        CREATE FUNCTION public.delete_tenant_user_membership(
            p_organization_id uuid,
            p_actor_id uuid,
            p_user_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            PERFORM public.assert_tenant_user_manager(p_organization_id, p_actor_id);
            UPDATE public.user_sessions AS session
            SET is_revoked = true
            WHERE session.organization_id = p_organization_id
              AND session.user_id = p_user_id
              AND NOT session.is_revoked;
            DELETE FROM public.organization_memberships AS membership
            WHERE membership.organization_id = p_organization_id
              AND membership.user_id = p_user_id;
            RETURN FOUND;
        END;
        $function$;

        REVOKE ALL ON FUNCTION public.assert_tenant_user_manager(uuid, uuid)
            FROM PUBLIC, nexus_app_user;
        REVOKE ALL ON FUNCTION public.create_tenant_user_membership(
            uuid, uuid, uuid, varchar, varchar, varchar, varchar
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.list_tenant_users(
            uuid, uuid, uuid, integer
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.set_tenant_user_membership_active(
            uuid, uuid, uuid, boolean
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.revoke_tenant_user_sessions(
            uuid, uuid, uuid
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.delete_tenant_user_membership(
            uuid, uuid, uuid
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.create_tenant_user_membership(
            uuid, uuid, uuid, varchar, varchar, varchar, varchar
        ) TO nexus_app_user;
        GRANT EXECUTE ON FUNCTION public.list_tenant_users(
            uuid, uuid, uuid, integer
        ) TO nexus_app_user;
        GRANT EXECUTE ON FUNCTION public.set_tenant_user_membership_active(
            uuid, uuid, uuid, boolean
        ) TO nexus_app_user;
        GRANT EXECUTE ON FUNCTION public.revoke_tenant_user_sessions(
            uuid, uuid, uuid
        ) TO nexus_app_user;
        GRANT EXECUTE ON FUNCTION public.delete_tenant_user_membership(
            uuid, uuid, uuid
        ) TO nexus_app_user;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION public.delete_tenant_user_membership(uuid, uuid, uuid);
        DROP FUNCTION public.revoke_tenant_user_sessions(uuid, uuid, uuid);
        DROP FUNCTION public.set_tenant_user_membership_active(
            uuid, uuid, uuid, boolean
        );
        DROP FUNCTION public.create_tenant_user_membership(
            uuid, uuid, uuid, varchar, varchar, varchar, varchar
        );
        DROP FUNCTION public.list_tenant_users(uuid, uuid, uuid, integer);
        DROP FUNCTION public.assert_tenant_user_manager(uuid, uuid);

        DROP POLICY users_tenant_select ON public.users;
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
        """
    )
