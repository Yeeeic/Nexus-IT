from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "migrations"
    / "versions"
    / "20260824_0012_devices_and_inventory.py"
)
ASSIGNMENT_MIGRATION = MIGRATION.with_name("20260824_0016_device_assignments.py")


def test_device_migration_forces_rls_and_composite_tenant_keys() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "20260824_0012"' in source
    assert 'down_revision: str | None = "20260824_0011"' in source
    assert source.count("FORCE ROW LEVEL SECURITY") == 3
    assert '["organization_id", "device_id"]' in source
    assert '["devices.organization_id", "devices.id"]' in source
    assert 'PrimaryKeyConstraint("organization_id", "id"' in source
    assert "token_secret" not in source


def test_device_token_lookup_role_receives_read_only_columns() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE POLICY device_tokens_auth_select" in source
    assert "GRANT SELECT (" in source
    assert "token_hash" in source
    assert "UPDATE ON TABLE public.device_tokens TO nexus_auth_user" not in source


def test_inventory_json_columns_are_type_and_size_bounded() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "pg_column_size(hardware) <= 65536" in source
    assert "pg_column_size(software_packages) <= 1048576" in source
    assert "pg_column_size(patches) <= 524288" in source
    assert "pg_column_size(services) <= 524288" in source


def test_device_assignment_has_composite_fks_rls_and_scoped_permissions() -> None:
    source = ASSIGNMENT_MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "20260824_0016"' in source
    assert 'down_revision: str | None = "20260824_0015"' in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert '["organization_id", "device_id"]' in source
    assert '["organization_id", "user_id"]' in source
    assert '"devices:read_all"' in source
    assert '"metrics:read_all"' in source
