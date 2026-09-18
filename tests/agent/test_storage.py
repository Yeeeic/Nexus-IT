from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

import pytest

from agent.nexus_agent.storage import LocalQueue, QueueCapacityExceeded
from agent.nexus_agent.protection import PayloadProtectionUnavailable


class TestProtector:
    def protect(self, plaintext: bytes) -> bytes:
        return b"encrypted:" + plaintext[::-1]

    def unprotect(self, ciphertext: bytes) -> bytes:
        return ciphertext.removeprefix(b"encrypted:")[::-1]


def make_queue(path: Path, **kwargs: object) -> LocalQueue:
    return LocalQueue(
        path,
        protector=TestProtector(),
        enforce_physical_quota=False,
        **kwargs,
    )


def test_queue_uses_wal_and_passes_integrity_check(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "state" / "agent.db")

    assert queue.journal_mode() == "wal"
    assert queue.integrity_check() == "ok"
    if os.name != "nt":
        assert stat.S_IMODE(queue.path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(queue.path.stat().st_mode) == 0o600


def test_fifo_evicts_old_periodic_batch_but_preserves_critical(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "agent.db", max_queue_bytes=50)
    old = queue.enqueue([{"value": "a" * 80}])
    critical = queue.enqueue([{"value": "b" * 80}], critical=True)
    newest = queue.enqueue([{"value": "c" * 80}])

    identifiers = []
    while (batch := queue.next_batch()) is not None:
        identifiers.append(batch.batch_id)
        queue.acknowledge(batch.batch_id)

    assert old not in identifiers
    assert critical in identifiers
    assert newest in identifiers


def test_queue_rejects_when_only_critical_data_can_be_preserved(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "agent.db", max_queue_bytes=40)
    queue.enqueue([{"value": "a" * 80}], critical=True)

    with pytest.raises(QueueCapacityExceeded):
        queue.enqueue([{"value": "b" * 80}], critical=True)

    assert queue.counts()["queued"] == 1


def test_corrupt_database_is_isolated_and_replaced(tmp_path: Path) -> None:
    path = tmp_path / "agent.db"
    path.write_bytes(b"not a sqlite database")
    diagnostics: list[tuple[str, object]] = []

    queue = LocalQueue(
        path,
        protector=TestProtector(),
        diagnostic=lambda code, details: diagnostics.append((code, details)),
    )

    assert queue.integrity_check() == "ok"
    assert len(list(tmp_path.glob("corrupt_*.db"))) == 1
    assert diagnostics[0][0] == "SQLITE_CORRUPTION_ISOLATED"


def test_expired_quarantine_payload_is_deleted_and_audited(tmp_path: Path) -> None:
    now = [1_000_000.0]
    queue = make_queue(
        tmp_path / "agent.db",
        quarantine_retention_days=14,
        clock=lambda: now[0],
    )
    identifier = queue.enqueue([{"cpu": 10}])
    batch = queue.next_batch()
    assert batch is not None and batch.batch_id == identifier
    queue.quarantine_batch(batch, error_code="HTTP_422_SCHEMA", error_summary="bad schema")

    connection = sqlite3.connect(queue.path)
    stored = connection.execute("SELECT encrypted_payload FROM batch_quarantine").fetchone()[0]
    connection.close()
    assert b'"cpu":10' not in stored

    now[0] += 14 * 86_400
    assert queue.purge_expired_quarantine() == 1
    assert queue.counts() == {"queued": 0, "batch_quarantine": 0, "sample_quarantine": 0, "audit": 2}


def test_quarantine_fails_closed_without_os_payload_protector(tmp_path: Path) -> None:
    queue = LocalQueue(tmp_path / "agent.db", enforce_physical_quota=False)
    identifier = queue.enqueue([{"cpu": 10}])
    batch = queue.next_batch()
    assert batch is not None and batch.batch_id == identifier

    with pytest.raises(PayloadProtectionUnavailable):
        queue.quarantine_batch(batch, error_code="HTTP_422_SCHEMA", error_summary="bad schema")

    assert queue.counts()["queued"] == 1
    assert queue.counts()["batch_quarantine"] == 0


@pytest.mark.parametrize("days", [0, 31])
def test_retention_never_accepts_values_outside_one_to_thirty_days(tmp_path: Path, days: int) -> None:
    with pytest.raises(ValueError):
        make_queue(tmp_path / "agent.db", quarantine_retention_days=days)
