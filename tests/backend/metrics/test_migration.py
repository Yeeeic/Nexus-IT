from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "migrations"
    / "versions"
    / "20260824_0013_metrics_alerts.py"
)


def test_metrics_migration_has_composite_isolation_and_partitioning() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260824_0012"' in source
    assert 'postgresql_partition_by="RANGE (recorded_at)"' in source
    assert '["organization_id", "device_id"]' in source
    assert '["devices.organization_id", "devices.id"]' in source
    assert "ALTER TABLE public.metric_batches FORCE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE public.metric_samples FORCE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE public.alert_rules FORCE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE public.alerts FORCE ROW LEVEL SECURITY" in source
