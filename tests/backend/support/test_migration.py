from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "migrations"
    / "versions"
    / "20260824_0014_support_and_remote_actions.py"
)


def test_support_migration_has_tenant_composite_keys_rls_and_closed_catalog() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260824_0013"' in source
    assert '["devices.organization_id", "devices.id"]' in source
    assert '["alerts.organization_id", "alerts.id"]' in source
    assert '["tickets.organization_id", "tickets.id"]' in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "organization_id = public.current_organization_id()" in source
    assert "run_shell" not in source
    for action_name in (
        "restart_service",
        "flush_dns",
        "collect_extended_diagnostics",
        "reboot_system",
    ):
        assert action_name in source


def test_support_migration_bounds_attachments_and_remote_results() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "file_size BETWEEN 1 AND 10485760" in source
    assert "octet_length(result_digest) = 32" in source
    assert "uq_action_executions_device_nonce" in source
    assert "PENDING_APPROVAL" in source
