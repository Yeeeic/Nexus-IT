from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "migrations"
    / "versions"
    / "20260830_0023_metric_retention_runtime.py"
)


def test_metric_maintenance_is_serialized_and_scopes_rls_per_tenant() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "pg_try_advisory_xact_lock" in source
    assert "FOR tenant_record IN" in source
    assert "app.current_organization_id" in source
    assert "tenant_record.id" in source
    assert "00000000-0000-0000-0000-000000000000" not in source
    assert "TO nexus_metrics_maintenance" in source
    assert "TO nexus_app_user" not in source
    assert "raw_samples_deleted', tenant_raw" in source
    assert "global_partitions_dropped', partitions_dropped" in source


def test_metric_maintenance_migrates_default_rows_before_attaching_daily_partition() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    move_position = source.index("DELETE FROM public.metric_samples_default")
    attach_position = source.index("ATTACH PARTITION public.%I")
    assert move_position < attach_position
    assert "FOR offset_days IN -14..14 LOOP" in source
