"""Static safety contracts for backup and PITR operational scripts.

These tests intentionally avoid Docker and existing volumes. The destructive
rehearsal remains an explicit, isolated workflow in ``pitr-rehearsal.sh``.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POSTGRES = ROOT / "infra" / "postgres"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_backups_use_streaming_cms_aes_gcm_not_openssl_enc() -> None:
    for name in ("backup-logical.sh", "backup-base.sh"):
        script = _read(POSTGRES / name)
        assert "openssl cms -encrypt" in script
        assert "-aes-256-gcm" in script
        assert "-stream" in script
        assert "openssl enc" not in script
        assert "set -Eeuo pipefail" in script
        assert "trap cleanup" in script


def test_base_backup_is_single_tablespace_stream_with_manifest() -> None:
    script = _read(POSTGRES / "backup-base.sh")
    assert "pg_tablespace" in script
    assert "spcname NOT IN ('pg_default', 'pg_global')" in script
    assert "--format=tar" in script
    assert "--wal-method=fetch" in script
    assert "--manifest-checksums=SHA256" in script
    assert "--pgdata=-" in script


def test_wal_archive_detects_conflicts_and_publishes_atomically() -> None:
    script = _read(POSTGRES / "pitr-archive-wal.sh")
    assert "sha256sum" in script
    assert "WAL archive conflict" in script
    assert "${wal_name}.ready" in script
    assert 'mv -T -- "${temporary_directory}" "${destination_directory}"' in script
    assert "openssl cms -encrypt" in script
    assert "-aes-256-gcm" in script


def test_restore_is_empty_target_only_and_pauses_before_promotion() -> None:
    script = _read(POSTGRES / "pitr-restore.sh")
    assert "NEXUS_PITR_TEST_ID" in script
    assert "/var/lib/postgresql/pitr-test" in script
    assert "Refusing non-empty PGDATA" in script
    assert "pg_verifybackup" in script
    assert "recovery_target_action = 'pause'" in script
    assert "recovery_target_timeline = 'latest'" in script
    assert "^[0-9]{4}-[0-9]{2}-[0-9]{2}T" in script
    assert "nexus-pitr-test-" in script
    assert 'mv "${PGDATA}"' not in script
    assert "PGDATA}.bak" not in script


def test_wal_restore_requires_authenticated_decryption_and_digest() -> None:
    script = _read(POSTGRES / "pitr-restore-wal.sh")
    assert "openssl cms -decrypt" in script
    assert "sha256sum --check" in script
    assert "mv --" in script


def test_archive_lag_thresholds_match_requirements() -> None:
    script = _read(POSTGRES / "pitr-check-archive-lag.sh")
    assert "NEXUS_WAL_WARNING_SECONDS:=600" in script
    assert "NEXUS_WAL_CRITICAL_SECONDS:=900" in script
    assert "pg_stat_archiver" in script


def test_pitr_compose_is_opt_in_and_test_stack_has_no_ports() -> None:
    overlay = _read(ROOT / "infra" / "compose.pitr.yaml")
    rehearsal = _read(ROOT / "infra" / "compose.pitr-test.yaml")
    assert "archive_mode=on" in overlay
    assert "pitr-archive-wal.sh" in overlay
    assert "external: true" in overlay
    assert "/usr/bin/env bash /opt/nexus/pitr-archive-wal.sh" in overlay
    assert "ports:" not in rehearsal
    assert "internal: true" in rehearsal
    assert "nexus-it_postgres_data" not in rehearsal
    assert "install -m 600 -o postgres -g postgres" in rehearsal
    assert "storage-init:" in rehearsal
    assert "condition: service_completed_successfully" in rehearsal
    assert "exec gosu postgres bash /opt/nexus/pitr-restore.sh" in rehearsal


def test_rehearsal_has_project_guard_and_explicit_cleanup() -> None:
    script = _read(ROOT / "tests" / "infra" / "pitr-rehearsal.sh")
    assert "nexus-pitr-test-" in script
    assert "Refusing unsafe Compose project" in script
    assert "down --volumes --remove-orphans" in script
    assert "nexus-it_postgres_data" in script


def test_monthly_workflow_is_manual_too_and_runs_rehearsal() -> None:
    workflow = _read(ROOT / ".github" / "workflows" / "pitr-restore.yml")
    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pitr-rehearsal.sh" in workflow
