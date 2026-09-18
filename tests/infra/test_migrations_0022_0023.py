import os
import pytest

from tests.infra.conftest import _run_sql


pytestmark = pytest.mark.skipif(
    os.getenv("NEXUS_RUN_DB_TESTS") != "1",
    reason="set NEXUS_RUN_DB_TESTS=1 to run Docker database tests",
)


def test_tenant_user_admin_functions_enforce_security_and_rls() -> None:
    rows = _run_sql(
        """
        BEGIN;
        -- Create tenant and user
        INSERT INTO public.organizations (id, slug, name, is_active)
        VALUES ('11111111-1111-4111-8111-111111111111', 'acme-test', 'Acme Test', true);

        INSERT INTO public.users (id, email, password_hash, full_name, is_active)
        VALUES (
            '22222222-2222-4222-8222-222222222222',
            'admin@acme.test',
            '$argon2id$v=19$m=65536,t=3,p=4$dummyhash',
            'Acme Admin',
            true
        );

        INSERT INTO public.organization_memberships (
            organization_id, user_id, is_active
        ) VALUES (
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222',
            true
        );

        -- Grant ADMIN role to admin in user_roles with system role_scope_id
        INSERT INTO public.user_roles (
            organization_id, user_id, role_scope_id, role_id
        )
        SELECT
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222',
            '00000000-0000-0000-0000-000000000000'::uuid,
            r.id
        FROM public.roles r
        WHERE r.name = 'ADMIN' AND r.is_system;

        -- Set RLS context for organization
        SELECT set_config('app.current_organization_id', '11111111-1111-4111-8111-111111111111', true);
        SET LOCAL ROLE nexus_app_user;

        -- Test list_tenant_users
        SELECT count(*)
        FROM public.list_tenant_users(
            '11111111-1111-4111-8111-111111111111'::uuid,
            '22222222-2222-4222-8222-222222222222'::uuid,
            NULL::uuid,
            50
        );

        -- Test create_tenant_user_membership with TECHNICIAN role string
        SELECT email
        FROM public.create_tenant_user_membership(
            '11111111-1111-4111-8111-111111111111'::uuid,
            '22222222-2222-4222-8222-222222222222'::uuid,
            '33333333-3333-4333-8333-333333333333'::uuid,
            'tech@acme.test',
            '$argon2id$v=19$m=65536,t=3,p=4$dummyhash',
            'Technician User',
            'TECHNICIAN'
        );

        -- Verify created user count
        SELECT count(*)
        FROM public.list_tenant_users(
            '11111111-1111-4111-8111-111111111111'::uuid,
            '22222222-2222-4222-8222-222222222222'::uuid,
            NULL::uuid,
            50
        );

        -- Test set_tenant_user_membership_active to false
        SELECT is_active
        FROM public.set_tenant_user_membership_active(
            '11111111-1111-4111-8111-111111111111'::uuid,
            '22222222-2222-4222-8222-222222222222'::uuid,
            '33333333-3333-4333-8333-333333333333'::uuid,
            false
        );

        ROLLBACK;
        """
    )
    assert "1" in rows
    assert "tech@acme.test" in rows
    assert "2" in rows
    assert "f" in rows


def test_metric_retention_runtime_maintenance_execution() -> None:
    rows = _run_sql(
        """
        BEGIN;
        -- Verify that nexus_app_user cannot execute maintenance function
        SET LOCAL ROLE nexus_app_user;
        DO $test$
        BEGIN
            BEGIN
                PERFORM public.run_metric_maintenance();
                RAISE EXCEPTION 'nexus_app_user should not have execute privilege';
            EXCEPTION
                WHEN insufficient_privilege THEN NULL;
            END;
        END
        $test$;

        -- Verify that nexus_metrics_maintenance CAN execute maintenance function
        SET LOCAL ROLE nexus_metrics_maintenance;
        SELECT public.run_metric_maintenance();

        -- Test advisory lock concurrency
        SELECT pg_try_advisory_xact_lock(1314084173, 1296389187);

        ROLLBACK;
        """
    )
    assert "t" in rows
