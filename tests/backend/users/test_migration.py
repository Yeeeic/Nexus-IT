from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "migrations"
    / "versions"
    / "20260830_0022_tenant_user_administration.py"
)


def test_tenant_user_functions_are_narrow_and_do_not_mutate_global_identities() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "SECURITY DEFINER" in source
    assert "SET search_path = pg_catalog, public" in source
    assert "permission.name = 'users:manage'" in source
    assert "AND actor.is_active" in source
    assert "role.is_system" in source
    assert "role.organization_id IS NULL" in source
    assert "session.organization_id = p_organization_id" in source
    assert "CREATE FUNCTION public.list_tenant_users" in source
    assert "AND membership.is_active" in source
    assert "DELETE FROM public.users" not in source
    assert "password_hash = EXCLUDED.password_hash" not in source
    assert "GRANT EXECUTE ON FUNCTION" in source
    assert "GRANT nexus_admin" not in source
