import os
import pytest

from tests.infra.conftest import _run_sql

pytestmark = pytest.mark.skipif(
    os.getenv("NEXUS_RUN_DB_TESTS") != "1",
    reason="set NEXUS_RUN_DB_TESTS=1 to run Docker database tests",
)


def test_runtime_role_and_organizations_table_are_hardened() -> None:
    rows = _run_sql(
        """
        SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin
        FROM pg_roles
        WHERE rolname IN ('nexus_admin', 'nexus_app_user')
        ORDER BY rolname;

        SELECT tableowner
        FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'organizations';

        SELECT relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE oid = 'public.organizations'::regclass;

        SELECT
            has_table_privilege('nexus_app_user', 'public.organizations', 'SELECT'),
            has_table_privilege('nexus_app_user', 'public.organizations', 'INSERT'),
            has_schema_privilege('nexus_app_user', 'public', 'CREATE');
        """
    )

    assert rows == [
        "nexus_admin|f|f|f|f|f",
        "nexus_app_user|f|f|f|f|f",
        "nexus_admin",
        "t|t",
        "t|f|f",
    ]


def test_login_runtime_principal_is_non_privileged_and_role_bounded() -> None:
    rows = _run_sql(
        """
        SELECT
            rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole,
            rolinherit, rolcanlogin
        FROM pg_roles
        WHERE rolname = 'nexus_runtime';

        SELECT string_agg(granted.rolname, ',' ORDER BY granted.rolname)
        FROM pg_auth_members AS membership
        JOIN pg_roles AS member ON member.oid = membership.member
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        WHERE member.rolname = 'nexus_runtime';
        """
    )

    assert rows == [
        "nexus_runtime|f|f|f|f|f|t",
        "nexus_app_user,nexus_auth_user",
    ]


def test_metrics_maintenance_uses_a_separate_non_privileged_principal() -> None:
    rows = _run_sql(
        """
        SELECT
            rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole,
            rolinherit, rolcanlogin
        FROM pg_roles
        WHERE rolname = 'nexus_maintenance_runtime';

        SELECT string_agg(granted.rolname, ',' ORDER BY granted.rolname)
        FROM pg_auth_members AS membership
        JOIN pg_roles AS member ON member.oid = membership.member
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        WHERE member.rolname = 'nexus_maintenance_runtime';

        SELECT
            has_function_privilege(
                'nexus_app_user', 'public.run_metric_maintenance()', 'EXECUTE'
            ),
            has_function_privilege(
                'nexus_metrics_maintenance',
                'public.run_metric_maintenance()',
                'EXECUTE'
            );
        """
    )

    assert rows == [
        "nexus_maintenance_runtime|f|f|f|f|f|t",
        "nexus_app_user,nexus_metrics_maintenance",
        "f|t",
    ]


def test_users_are_visible_only_through_active_tenant_membership() -> None:
    rows = _run_sql(
        """
        SELECT relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE oid = 'public.users'::regclass;

        BEGIN;
        INSERT INTO public.organizations (id, slug, name)
        VALUES
          ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'users-test-a', 'Users A'),
          ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'users-test-b', 'Users B');
        INSERT INTO public.users (id, email, password_hash, full_name)
        VALUES
          (
            'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
            'user-a@example.test', '$argon2id$test', 'User A'
          ),
          (
            'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
            'user-b@example.test', '$argon2id$test', 'User B'
          );
        INSERT INTO public.organization_memberships (
            organization_id, user_id, is_active
        )
        VALUES
          (
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'cccccccc-cccc-4ccc-8ccc-cccccccccccc', true
          ),
          (
            'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            'dddddddd-dddd-4ddd-8ddd-dddddddddddd', false
          );

        SET LOCAL ROLE nexus_app_user;
        SET LOCAL app.current_organization_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        SELECT string_agg(email, ',' ORDER BY email) FROM public.users;
        SET LOCAL app.current_organization_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
        SELECT string_agg(email, ',' ORDER BY email) FROM public.users;
        ROLLBACK;
        """
    )

    assert rows == [
        "t|t",
        "BEGIN",
        "INSERT 0 2",
        "INSERT 0 2",
        "INSERT 0 2",
        "SET",
        "SET",
        "user-a@example.test",
        "SET",
        "ROLLBACK",
    ]


def test_rls_isolates_organizations_and_transaction_context() -> None:
    rows = _run_sql(
        """
        BEGIN;
        INSERT INTO public.organizations (id, slug, name)
        VALUES
          ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'rls-test-a', 'RLS Test A'),
          ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'rls-test-b', 'RLS Test B');

        SET LOCAL ROLE nexus_app_user;
        SET LOCAL app.current_organization_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

        SELECT string_agg(slug, ',' ORDER BY slug)
        FROM public.organizations;

        WITH changed AS (
            UPDATE public.organizations
            SET name = 'Cross-tenant modification'
            WHERE id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
            RETURNING id
        )
        SELECT count(*) FROM changed;

        SELECT public.current_organization_id();
        ROLLBACK;

        SELECT public.current_organization_id() IS NULL;

        BEGIN;
        SET LOCAL ROLE nexus_app_user;
        SET LOCAL app.current_organization_id = 'not-a-uuid';
        SELECT public.current_organization_id() IS NULL;
        ROLLBACK;
        """
    )

    assert rows == [
        "BEGIN",
        "INSERT 0 2",
        "SET",
        "SET",
        "rls-test-a",
        "0",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "ROLLBACK",
        "t",
        "BEGIN",
        "SET",
        "SET",
        "t",
        "ROLLBACK",
    ]


def test_auth_tables_are_owned_and_restricted() -> None:
    rows = _run_sql(
        """
        SELECT tablename, tableowner
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename IN ('users', 'organization_memberships', 'user_sessions')
        ORDER BY tablename;

        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class AS c
        WHERE c.oid IN (
            'public.organization_memberships'::regclass,
            'public.user_sessions'::regclass
        )
        ORDER BY c.relname;

        SELECT
            has_table_privilege('nexus_app_user', 'public.users', 'SELECT'),
            has_table_privilege(
                'nexus_app_user', 'public.organization_memberships', 'SELECT'
            ),
            has_table_privilege('nexus_app_user', 'public.user_sessions', 'SELECT'),
            has_table_privilege('nexus_app_user', 'public.user_sessions', 'UPDATE');
        """
    )

    assert rows == [
        "organization_memberships|nexus_admin",
        "user_sessions|nexus_admin",
        "users|nexus_admin",
        "organization_memberships|t|t",
        "user_sessions|t|t",
        "f|t|t|f",
    ]


def test_membership_fk_and_rls_reject_cross_tenant_sessions() -> None:
    rows = _run_sql(
        """
        BEGIN;
        INSERT INTO public.organizations (id, slug, name)
        VALUES
          ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'auth-test-a', 'Auth Test A'),
          ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'auth-test-b', 'Auth Test B');
        INSERT INTO public.users (id, email, password_hash, full_name)
        VALUES (
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
          'member@example.test',
          '$argon2id$test',
          'Test Member'
        );
        INSERT INTO public.organization_memberships (organization_id, user_id)
        VALUES (
          'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        );
        INSERT INTO public.user_sessions (
          id, organization_id, user_id, session_token_hash, csrf_token_hash,
          expires_at, last_seen_at
        ) VALUES (
          'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
          'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
          decode(repeat('aa', 32), 'hex'),
          decode(repeat('bb', 32), 'hex'),
          CURRENT_TIMESTAMP + interval '1 hour',
          CURRENT_TIMESTAMP
        );

        DO $test$
        BEGIN
          BEGIN
            INSERT INTO public.user_sessions (
              id, organization_id, user_id, session_token_hash, csrf_token_hash,
              expires_at, last_seen_at
            ) VALUES (
              'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
              'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
              decode(repeat('cc', 32), 'hex'),
              decode(repeat('dd', 32), 'hex'),
              CURRENT_TIMESTAMP + interval '1 hour',
              CURRENT_TIMESTAMP
            );
            RAISE EXCEPTION 'cross-tenant session was accepted';
          EXCEPTION WHEN foreign_key_violation THEN
            NULL;
          END;
        END
        $test$;

        SET LOCAL ROLE nexus_app_user;
        SET LOCAL app.current_organization_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        SELECT count(*) FROM public.organization_memberships;
        SELECT count(*) FROM public.user_sessions;
        SET LOCAL app.current_organization_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
        SELECT count(*) FROM public.organization_memberships;
        SELECT count(*) FROM public.user_sessions;
        ROLLBACK;
        """
    )

    assert rows == [
        "BEGIN",
        "INSERT 0 2",
        "INSERT 0 1",
        "INSERT 0 1",
        "INSERT 0 1",
        "DO",
        "SET",
        "SET",
        "1",
        "1",
        "SET",
        "0",
        "0",
        "ROLLBACK",
    ]


def test_rbac_tables_are_hardened_and_read_only_for_runtime_role() -> None:
    rows = _run_sql(
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class AS c
        WHERE c.oid IN (
            'public.roles'::regclass,
            'public.role_permissions'::regclass,
            'public.user_roles'::regclass
        )
        ORDER BY c.relname;

        SELECT
            has_table_privilege('nexus_app_user', 'public.roles', 'SELECT'),
            has_table_privilege('nexus_app_user', 'public.roles', 'INSERT'),
            has_table_privilege('nexus_app_user', 'public.permissions', 'SELECT'),
            has_table_privilege('nexus_app_user', 'public.user_roles', 'SELECT'),
            has_table_privilege('nexus_app_user', 'public.user_roles', 'INSERT');
        """
    )

    assert rows == [
        "role_permissions|t|t",
        "roles|t|t",
        "user_roles|t|t",
        "t|f|t|t|f",
    ]


def test_rbac_scope_rejects_cross_tenant_role_assignment() -> None:
    rows = _run_sql(
        """
        BEGIN;
        INSERT INTO public.organizations (id, slug, name)
        VALUES
          ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'rbac-test-a', 'RBAC Test A'),
          ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'rbac-test-b', 'RBAC Test B');
        INSERT INTO public.users (id, email, password_hash, full_name)
        VALUES (
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
          'rbac@example.test',
          '$argon2id$test',
          'RBAC Member'
        );
        INSERT INTO public.organization_memberships (organization_id, user_id)
        VALUES (
          'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        );
        INSERT INTO public.roles (id, organization_id, name, description, is_system)
        VALUES
          (
            '22222222-2222-4222-8222-222222222222',
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'Custom A', 'Custom role for A', false
          ),
          (
            '33333333-3333-4333-8333-333333333333',
            'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            'Custom B', 'Custom role for B', false
          );
        INSERT INTO public.role_permissions (
          role_scope_id, role_id, permission_id
        ) VALUES
          (
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            '22222222-2222-4222-8222-222222222222',
            '20000000-0000-4000-8000-000000000001'
          ),
          (
            'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            '33333333-3333-4333-8333-333333333333',
            '20000000-0000-4000-8000-000000000001'
          );
        INSERT INTO public.user_roles (
          organization_id, user_id, role_scope_id, role_id
        ) VALUES
          (
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
            '00000000-0000-0000-0000-000000000000',
            '10000000-0000-4000-8000-000000000001'
          ),
          (
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            '22222222-2222-4222-8222-222222222222'
          );

        DO $test$
        BEGIN
          BEGIN
            INSERT INTO public.user_roles (
              organization_id, user_id, role_scope_id, role_id
            ) VALUES (
              'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
              'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
              'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              '33333333-3333-4333-8333-333333333333'
            );
            RAISE EXCEPTION 'cross-tenant role was accepted';
          EXCEPTION WHEN check_violation OR foreign_key_violation THEN
            NULL;
          END;
        END
        $test$;

        SET LOCAL ROLE nexus_app_user;
        SET LOCAL app.current_organization_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        SELECT string_agg(name, ',' ORDER BY name) FROM public.roles;
        SELECT count(*) FROM public.role_permissions;
        SELECT count(*) FROM public.user_roles;
        SET LOCAL app.current_organization_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
        SELECT string_agg(name, ',' ORDER BY name) FROM public.roles;
        SELECT count(*) FROM public.user_roles;
        ROLLBACK;
        """
    )

    assert rows == [
        "BEGIN",
        "INSERT 0 2",
        "INSERT 0 1",
        "INSERT 0 1",
        "INSERT 0 2",
        "INSERT 0 2",
        "INSERT 0 2",
        "DO",
        "SET",
        "SET",
        "ADMIN,Custom A,READER,TECHNICIAN",
        "47",
        "2",
        "SET",
        "ADMIN,Custom B,READER,TECHNICIAN",
        "0",
        "ROLLBACK",
    ]


def test_system_roles_match_canonical_permission_matrix() -> None:
    rows = _run_sql(
        """
        SELECT string_agg(name, ',' ORDER BY name)
        FROM public.roles
        WHERE is_system AND organization_id IS NULL;

        SELECT count(*) FROM public.permissions;

        SELECT r.name, count(*)
        FROM public.roles AS r
        JOIN public.role_permissions AS rp ON rp.role_id = r.id
        WHERE r.is_system
        GROUP BY r.name
        ORDER BY r.name;

        SELECT count(*)
        FROM public.role_permissions AS rp
        JOIN public.permissions AS p ON p.id = rp.permission_id
        WHERE p.name IN (
            'metrics:ingest_batch',
            'inventory:write',
            'actions:agent_poll_ack'
        );
        """
    )

    assert rows == [
        "ADMIN,READER,TECHNICIAN",
        "28",
        "ADMIN|25",
        "READER|6",
        "TECHNICIAN|15",
        "0",
    ]


def test_auth_role_has_only_required_global_identity_privileges() -> None:
    rows = _run_sql(
        """
        SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin
        FROM pg_roles
        WHERE rolname = 'nexus_auth_user';

        SELECT
            has_column_privilege('nexus_auth_user', 'public.users', 'id', 'SELECT'),
            has_column_privilege(
                'nexus_auth_user', 'public.users', 'password_hash', 'SELECT'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.users', 'full_name', 'SELECT'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.users', 'password_hash', 'UPDATE'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.users', 'failed_login_attempts', 'UPDATE'
            ),
            has_table_privilege(
                'nexus_auth_user', 'public.organization_memberships', 'SELECT'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.organizations', 'name', 'SELECT'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.organizations', 'slug', 'SELECT'
            );
        """
    )

    assert rows == [
        "nexus_auth_user|f|f|f|f|f",
        "t|t|t|t|t|t|t|f",
    ]


def test_auth_role_lists_only_memberships_for_verified_user_context() -> None:
    rows = _run_sql(
        """
        BEGIN;
        INSERT INTO public.organizations (id, slug, name)
        VALUES
          ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'login-test-a', 'Login Test A'),
          ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'login-test-b', 'Login Test B');
        INSERT INTO public.users (id, email, password_hash, full_name)
        VALUES
          (
            'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
            'login-a@example.test', '$argon2id$test', 'Login A'
          ),
          (
            'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
            'login-b@example.test', '$argon2id$test', 'Login B'
          );
        INSERT INTO public.organization_memberships (organization_id, user_id)
        VALUES
          (
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
          ),
          (
            'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
          );

        SET LOCAL ROLE nexus_auth_user;
        SET LOCAL app.current_user_id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
        SELECT string_agg(name, ',' ORDER BY name) FROM public.organizations;
        SELECT count(*) FROM public.organization_memberships;
        SET LOCAL app.current_user_id = 'not-a-uuid';
        SELECT count(id) FROM public.organizations;
        SELECT count(*) FROM public.organization_memberships;
        ROLLBACK;
        """
    )

    assert rows == [
        "BEGIN",
        "INSERT 0 2",
        "INSERT 0 2",
        "INSERT 0 2",
        "SET",
        "SET",
        "Login Test A",
        "1",
        "SET",
        "0",
        "0",
        "ROLLBACK",
    ]


def test_auth_role_has_token_scoped_session_privileges() -> None:
    rows = _run_sql(
        """
        SELECT
            has_function_privilege(
                'nexus_auth_user',
                'public.current_session_token_hash()',
                'EXECUTE'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.user_sessions', 'id', 'SELECT'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.user_sessions',
                'session_token_hash', 'SELECT'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.user_sessions',
                'session_token_hash', 'INSERT'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.user_sessions',
                'organization_id', 'UPDATE'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.user_sessions',
                'is_revoked', 'UPDATE'
            );

        SELECT string_agg(policyname, ',' ORDER BY policyname)
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'user_sessions'
          AND 'nexus_auth_user' = ANY(roles);
        """
    )

    assert rows == [
        "t|t|f|t|f|t",
        (
            "sessions_authenticated_user_insert,"
            "sessions_authenticated_user_select,"
            "sessions_authenticated_user_update"
        ),
    ]


def test_auth_sessions_are_scoped_to_verified_user_and_presented_token() -> None:
    rows = _run_sql(
        """
        BEGIN;
        INSERT INTO public.organizations (id, slug, name)
        VALUES
          ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'session-test-a', 'Session A'),
          ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'session-test-b', 'Session B');
        INSERT INTO public.users (id, email, password_hash, full_name)
        VALUES (
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
          'session@example.test', '$argon2id$test', 'Session User'
        );
        INSERT INTO public.organization_memberships (organization_id, user_id)
        VALUES (
          'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        );

        SET LOCAL ROLE nexus_auth_user;
        SET LOCAL app.current_user_id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
        INSERT INTO public.user_sessions (
          id, organization_id, user_id, session_token_hash, csrf_token_hash,
          expires_at, last_seen_at
        ) VALUES (
          'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
          'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
          decode(repeat('aa', 32), 'hex'),
          decode(repeat('bb', 32), 'hex'),
          CURRENT_TIMESTAMP + interval '1 hour', CURRENT_TIMESTAMP
        );

        SET LOCAL app.current_user_id = '';
        SET LOCAL app.current_session_token_hash =
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
        SELECT count(*) FROM public.user_sessions;

        SET LOCAL app.current_user_id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
        WITH changed AS (
          UPDATE public.user_sessions
          SET is_revoked = true
          RETURNING id
        )
        SELECT count(*) FROM changed;

        SET LOCAL app.current_session_token_hash = 'not-a-hash';
        SELECT public.current_session_token_hash() IS NULL;
        SELECT count(*) FROM public.user_sessions;

        DO $test$
        BEGIN
          BEGIN
            INSERT INTO public.user_sessions (
              id, organization_id, user_id, session_token_hash, csrf_token_hash,
              expires_at, last_seen_at
            ) VALUES (
              'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
              'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
              decode(repeat('cc', 32), 'hex'),
              decode(repeat('dd', 32), 'hex'),
              CURRENT_TIMESTAMP + interval '1 hour', CURRENT_TIMESTAMP
            );
            RAISE EXCEPTION 'cross-tenant session was accepted';
          EXCEPTION
            WHEN insufficient_privilege OR foreign_key_violation THEN NULL;
          END;
        END
        $test$;
        ROLLBACK;
        """
    )

    assert rows == [
        "BEGIN",
        "INSERT 0 2",
        "INSERT 0 1",
        "INSERT 0 1",
        "SET",
        "SET",
        "INSERT 0 1",
        "SET",
        "SET",
        "1",
        "SET",
        "1",
        "SET",
        "t",
        "0",
        "DO",
        "ROLLBACK",
    ]


def test_audit_log_is_partitioned_forced_rls_and_append_only() -> None:
    rows = _run_sql(
        """
        SELECT relkind, relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE oid = 'public.audit_logs'::regclass;

        SELECT count(*)
        FROM pg_inherits
        WHERE inhparent = 'public.audit_logs'::regclass;

        SELECT
            has_column_privilege(
                'nexus_app_user', 'public.audit_logs', 'details', 'INSERT'
            ),
            has_column_privilege(
                'nexus_app_user', 'public.audit_logs', 'created_at', 'INSERT'
            ),
            has_table_privilege(
                'nexus_app_user', 'public.audit_logs', 'SELECT'
            ),
            has_table_privilege(
                'nexus_app_user', 'public.audit_logs', 'UPDATE'
            ),
            has_table_privilege(
                'nexus_app_user', 'public.audit_logs', 'DELETE'
            ),
            has_column_privilege(
                'nexus_auth_user', 'public.audit_logs', 'action', 'INSERT'
            ),
            has_table_privilege(
                'nexus_auth_user', 'public.audit_logs', 'SELECT'
            );

        SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
        FROM pg_roles
        WHERE rolname = 'nexus_audit_admin';
        """
    )

    assert rows == [
        "p|t|t",
        "3",
        "t|f|t|f|f|t|f",
        "nexus_audit_admin|f|f|f",
    ]


def test_auth_role_can_append_only_bounded_global_login_events() -> None:
    rows = _run_sql(
        """
        BEGIN;
        SET LOCAL ROLE nexus_auth_user;
        INSERT INTO public.audit_logs (
          id, organization_id, actor_id, actor_type, ip_address, user_agent,
          action, resource_type, resource_id, status, details
        ) VALUES (
          'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', NULL, NULL, 'SYSTEM',
          '192.0.2.10', 'Browser/1.0', 'AUTH.LOGIN_FAILURE', 'USER', NULL,
          'FAILURE', '{"reason":"INVALID_CREDENTIALS"}'::jsonb
        );
        INSERT INTO public.audit_logs (
          id, organization_id, actor_id, actor_type, ip_address, user_agent,
          action, resource_type, resource_id, status, details
        ) VALUES (
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc', NULL, NULL, 'SYSTEM',
          '192.0.2.10', 'Browser/1.0', 'AUTH.LOGOUT', 'SESSION', NULL,
          'SUCCESS', '{"result":"REVOKED"}'::jsonb
        );

        DO $test$
        BEGIN
          BEGIN
            INSERT INTO public.audit_logs (
              id, organization_id, actor_id, actor_type, action,
              resource_type, status, details
            ) VALUES (
              'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', NULL, NULL, 'SYSTEM',
              'TICKET.DELETE', 'TICKET', 'DENIED', '{}'::jsonb
            );
            RAISE EXCEPTION 'non-auth global audit event was accepted';
          EXCEPTION
            WHEN insufficient_privilege OR check_violation THEN NULL;
          END;
        END
        $test$;
        ROLLBACK;
        """
    )

    assert rows == [
        "BEGIN",
        "SET",
        "INSERT 0 1",
        "INSERT 0 1",
        "DO",
        "ROLLBACK",
    ]
