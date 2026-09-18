"""Durable SQLite WAL queue with bounded FIFO retention and quarantine."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
import uuid
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

from .compat import dataclass

from .permissions import harden_directory, harden_file
from .protection import PayloadProtector, UnavailablePayloadProtector


LOGGER = logging.getLogger(__name__)
MAX_QUEUE_BYTES = 500 * 1024 * 1024
MAX_QUARANTINE_BYTES = 50 * 1024 * 1024
MAX_RETENTION_DAYS = 30


class QueueCapacityExceeded(RuntimeError):
    """Raised when bounded storage cannot accept data without losing protected records."""


@dataclass(frozen=True, slots=True)
class StoredBatch:
    batch_id: str
    samples: tuple[Mapping[str, object], ...]
    parent_batch_id: str | None
    split_depth: int
    attempts: int
    created_at: int


class LocalQueue:
    def __init__(
        self,
        path: Path | str,
        *,
        protector: PayloadProtector | None = None,
        max_queue_bytes: int = MAX_QUEUE_BYTES,
        max_quarantine_bytes: int = MAX_QUARANTINE_BYTES,
        quarantine_retention_days: int = 14,
        clock: Callable[[], float] = time.time,
        diagnostic: Callable[[str, Mapping[str, object]], None] | None = None,
        enforce_physical_quota: bool = True,
    ) -> None:
        if max_queue_bytes <= 0 or max_queue_bytes > MAX_QUEUE_BYTES:
            raise ValueError("max_queue_bytes must be between 1 and 500 MB")
        if max_quarantine_bytes <= 0 or max_quarantine_bytes > MAX_QUARANTINE_BYTES:
            raise ValueError("max_quarantine_bytes must be between 1 and 50 MB")
        if not 1 <= quarantine_retention_days <= MAX_RETENTION_DAYS:
            raise ValueError("quarantine retention must be between 1 and 30 days")
        self.path = Path(path)
        self._protector = protector or UnavailablePayloadProtector()
        self._max_queue_bytes = max_queue_bytes
        self._max_quarantine_bytes = max_quarantine_bytes
        self._retention_seconds = quarantine_retention_days * 86_400
        self._clock = clock
        self._diagnostic = diagnostic or self._log_diagnostic
        self._enforce_physical_quota = enforce_physical_quota
        harden_directory(self.path.parent)
        self._isolate_if_corrupt()
        self._initialize()

    @staticmethod
    def _log_diagnostic(code: str, details: Mapping[str, object]) -> None:
        LOGGER.error("agent diagnostic %s %s", code, dict(details))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _isolate_if_corrupt(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        healthy = False
        try:
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=2)
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
                healthy = bool(row and row[0] == "ok")
            finally:
                connection.close()
        except sqlite3.DatabaseError:
            healthy = False
        if healthy:
            return
        timestamp = int(self._clock())
        isolated = self.path.with_name(f"corrupt_{timestamp}.db")
        sequence = 1
        while isolated.exists():
            isolated = self.path.with_name(f"corrupt_{timestamp}_{sequence}.db")
            sequence += 1
        self.path.replace(isolated)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.path}{suffix}")
            if sidecar.exists():
                sidecar.replace(Path(f"{isolated}{suffix}"))
        harden_file(isolated)
        self._diagnostic("SQLITE_CORRUPTION_ISOLATED", {"isolated_name": isolated.name})

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS queued_batches (
                    batch_id TEXT PRIMARY KEY,
                    parent_batch_id TEXT,
                    payload BLOB NOT NULL,
                    payload_size INTEGER NOT NULL CHECK (payload_size >= 0),
                    critical INTEGER NOT NULL DEFAULT 0 CHECK (critical IN (0, 1)),
                    split_depth INTEGER NOT NULL DEFAULT 0 CHECK (split_depth BETWEEN 0 AND 3),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                    next_attempt_at INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_queued_batches_dispatch
                    ON queued_batches(next_attempt_at, created_at);
                CREATE TABLE IF NOT EXISTS batch_quarantine (
                    batch_id TEXT PRIMARY KEY,
                    encrypted_payload BLOB,
                    encrypted_size INTEGER NOT NULL,
                    error_code TEXT NOT NULL,
                    error_summary TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK (state = 'QUARANTINED'),
                    created_at INTEGER NOT NULL,
                    purge_after INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sample_quarantine (
                    sample_id TEXT PRIMARY KEY,
                    parent_batch_id TEXT NOT NULL,
                    encrypted_payload BLOB,
                    encrypted_size INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    purge_after INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_audit (
                    id TEXT PRIMARY KEY,
                    event TEXT NOT NULL,
                    resource_id TEXT,
                    details_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                """
            )
        finally:
            connection.close()
        harden_file(self.path)

    @staticmethod
    def _encode(samples: Sequence[Mapping[str, object]]) -> tuple[bytes, bytes]:
        raw = json.dumps(
            list(samples), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return raw, zlib.compress(raw, level=6)

    @staticmethod
    def _decode(payload: bytes) -> tuple[Mapping[str, object], ...]:
        value = json.loads(zlib.decompress(payload))
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError("stored batch payload has invalid shape")
        return tuple(value)

    def enqueue(
        self,
        samples: Sequence[Mapping[str, object]],
        *,
        batch_id: str | None = None,
        parent_batch_id: str | None = None,
        split_depth: int = 0,
        critical: bool = False,
    ) -> str:
        if not samples:
            raise ValueError("batch must contain at least one sample")
        if not 0 <= split_depth <= 3:
            raise ValueError("split_depth must be between 0 and 3")
        identifier = batch_id or str(uuid.uuid4())
        uuid.UUID(identifier)
        if parent_batch_id is not None:
            uuid.UUID(parent_batch_id)
        _, compressed = self._encode(samples)
        now = int(self._clock())
        with self._transaction() as connection:
            self._make_room(connection, len(compressed))
            connection.execute(
                """INSERT INTO queued_batches
                   (batch_id, parent_batch_id, payload, payload_size, critical, split_depth, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (identifier, parent_batch_id, compressed, len(compressed), int(critical), split_depth, now),
            )
        self._enforce_disk_bound()
        connection = self._connect()
        try:
            persisted = connection.execute(
                "SELECT 1 FROM queued_batches WHERE batch_id = ?", (identifier,)
            ).fetchone()
        finally:
            connection.close()
        if persisted is None:
            raise QueueCapacityExceeded("payload could not fit within physical SQLite quota")
        return identifier

    def _queue_bytes(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT COALESCE(SUM(payload_size), 0) FROM queued_batches").fetchone()
        return int(row[0])

    def _make_room(self, connection: sqlite3.Connection, required: int) -> None:
        if required > self._max_queue_bytes:
            raise QueueCapacityExceeded("single payload exceeds local queue quota")
        while self._queue_bytes(connection) + self._quarantine_bytes(connection) + required > self._max_queue_bytes:
            row = connection.execute(
                "SELECT batch_id FROM queued_batches WHERE critical = 0 ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if row is None:
                raise QueueCapacityExceeded("queue contains only protected critical records")
            connection.execute("DELETE FROM queued_batches WHERE batch_id = ?", (row[0],))
            self._audit(connection, "QUEUE_FIFO_EVICTION", row[0], {"cause": "QUEUE_QUOTA"})

    def _disk_bytes(self) -> int:
        return sum(
            candidate.stat().st_size
            for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm"))
            if candidate.exists()
        )

    def _enforce_disk_bound(self) -> None:
        if not self._enforce_physical_quota:
            return
        if self._disk_bytes() <= self._max_queue_bytes:
            return
        connection = self._connect()
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA incremental_vacuum")
        finally:
            connection.close()
        while self._disk_bytes() > self._max_queue_bytes:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT batch_id FROM queued_batches WHERE critical = 0 ORDER BY created_at, rowid LIMIT 1"
                ).fetchone()
                if row is None:
                    raise QueueCapacityExceeded("physical SQLite files exceed queue quota")
                connection.execute("DELETE FROM queued_batches WHERE batch_id = ?", (row[0],))
                self._audit(connection, "QUEUE_FIFO_EVICTION", row[0], {"cause": "PHYSICAL_QUOTA"})
            connection = self._connect()
            try:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("PRAGMA incremental_vacuum")
            finally:
                connection.close()

    def next_batch(self, *, now: int | None = None) -> StoredBatch | None:
        effective_now = int(self._clock()) if now is None else now
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT batch_id, parent_batch_id, payload, split_depth, attempts, created_at
                   FROM queued_batches WHERE next_attempt_at <= ?
                   ORDER BY created_at, rowid LIMIT 1""",
                (effective_now,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return StoredBatch(
            batch_id=row["batch_id"], samples=self._decode(row["payload"]),
            parent_batch_id=row["parent_batch_id"], split_depth=row["split_depth"],
            attempts=row["attempts"], created_at=row["created_at"],
        )

    def get_batch(self, batch_id: str) -> StoredBatch | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT batch_id, parent_batch_id, payload, split_depth, attempts, created_at
                   FROM queued_batches WHERE batch_id = ?""",
                (batch_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return StoredBatch(
            batch_id=row["batch_id"], samples=self._decode(row["payload"]),
            parent_batch_id=row["parent_batch_id"], split_depth=row["split_depth"],
            attempts=row["attempts"], created_at=row["created_at"],
        )

    def queued_batch_ids(self, limit: int = 50) -> tuple[str, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT batch_id FROM queued_batches ORDER BY created_at LIMIT ?", (limit,)
            ).fetchall()
            return tuple(row[0] for row in rows)
        finally:
            connection.close()

    def acknowledge(self, batch_id: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute("DELETE FROM queued_batches WHERE batch_id = ?", (batch_id,))
            return cursor.rowcount == 1

    def defer(self, batch_id: str, *, delay_seconds: int) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        with self._transaction() as connection:
            connection.execute(
                """UPDATE queued_batches SET attempts = attempts + 1, next_attempt_at = ?
                   WHERE batch_id = ?""",
                (int(self._clock()) + delay_seconds, batch_id),
            )

    def split(self, batch: StoredBatch) -> tuple[str, str]:
        if len(batch.samples) < 2 or batch.split_depth >= 3:
            raise ValueError("batch cannot be split")
        midpoint = len(batch.samples) // 2
        children = (batch.samples[:midpoint], batch.samples[midpoint:])
        identifiers = (str(uuid.uuid4()), str(uuid.uuid4()))
        encoded = [self._encode(child)[1] for child in children]
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT critical FROM queued_batches WHERE batch_id = ?", (batch.batch_id,)
            ).fetchone()
            if existing is None:
                raise KeyError(batch.batch_id)
            connection.execute("DELETE FROM queued_batches WHERE batch_id = ?", (batch.batch_id,))
            for identifier, payload in zip(identifiers, encoded, strict=True):
                self._make_room(connection, len(payload))
                connection.execute(
                    """INSERT INTO queued_batches
                       (batch_id, parent_batch_id, payload, payload_size, critical, split_depth, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        identifier, batch.batch_id, payload, len(payload), existing["critical"],
                        batch.split_depth + 1, int(self._clock()),
                    ),
                )
        return identifiers

    @staticmethod
    def _safe_summary(summary: str) -> str:
        del summary
        return "Batch rejected by server; inspect protected server diagnostics"

    @staticmethod
    def _safe_error_code(error_code: str) -> str:
        normalized = error_code.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", normalized):
            return "REMOTE_REJECTION"
        return normalized

    def quarantine_batch(self, batch: StoredBatch, *, error_code: str, error_summary: str) -> None:
        raw, _ = self._encode(batch.samples)
        encrypted = self._protector.protect(raw)
        now = int(self._clock())
        safe_code = self._safe_error_code(error_code)
        with self._transaction() as connection:
            self._purge_expired(connection, now)
            cursor = connection.execute("DELETE FROM queued_batches WHERE batch_id = ?", (batch.batch_id,))
            if cursor.rowcount != 1:
                raise KeyError(batch.batch_id)
            self._make_room(connection, len(encrypted))
            self._ensure_quarantine_room(connection, len(encrypted))
            connection.execute(
                """INSERT INTO batch_quarantine
                   (batch_id, encrypted_payload, encrypted_size, error_code, error_summary,
                    payload_digest, sample_count, state, created_at, purge_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'QUARANTINED', ?, ?)""",
                (
                    batch.batch_id, encrypted, len(encrypted), safe_code,
                    self._safe_summary(error_summary), hashlib.sha256(raw).hexdigest(),
                    len(batch.samples), now, now + self._retention_seconds,
                ),
            )
            event = "BATCH_QUARANTINED_422" if safe_code.startswith("HTTP_422") else "BATCH_QUARANTINED_TERMINAL"
            self._audit(connection, event, batch.batch_id, {"error_code": safe_code})

    def quarantine_sample(self, batch: StoredBatch, *, reason: str) -> str:
        if len(batch.samples) != 1:
            raise ValueError("sample quarantine requires exactly one sample")
        raw, _ = self._encode(batch.samples)
        encrypted = self._protector.protect(raw)
        now = int(self._clock())
        sample_id = str(uuid.uuid4())
        with self._transaction() as connection:
            self._purge_expired(connection, now)
            cursor = connection.execute("DELETE FROM queued_batches WHERE batch_id = ?", (batch.batch_id,))
            if cursor.rowcount != 1:
                raise KeyError(batch.batch_id)
            self._make_room(connection, len(encrypted))
            self._ensure_quarantine_room(connection, len(encrypted))
            connection.execute(
                """INSERT INTO sample_quarantine
                   (sample_id, parent_batch_id, encrypted_payload, encrypted_size, reason,
                    payload_digest, created_at, purge_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sample_id, batch.batch_id, encrypted, len(encrypted), reason[:64],
                    hashlib.sha256(raw).hexdigest(), now, now + self._retention_seconds,
                ),
            )
            self._audit(connection, "SAMPLE_QUARANTINED_413", sample_id, {"parent_batch_id": batch.batch_id})
        return sample_id

    def _quarantine_bytes(self, connection: sqlite3.Connection) -> int:
        batch = connection.execute("SELECT COALESCE(SUM(encrypted_size), 0) FROM batch_quarantine").fetchone()[0]
        sample = connection.execute("SELECT COALESCE(SUM(encrypted_size), 0) FROM sample_quarantine").fetchone()[0]
        return int(batch) + int(sample)

    def _ensure_quarantine_room(self, connection: sqlite3.Connection, required: int) -> None:
        if required > self._max_quarantine_bytes or self._quarantine_bytes(connection) + required > self._max_quarantine_bytes:
            raise QueueCapacityExceeded("quarantine quota exhausted")

    def purge_expired_quarantine(self) -> int:
        with self._transaction() as connection:
            return self._purge_expired(connection, int(self._clock()))

    def _purge_expired(self, connection: sqlite3.Connection, now: int) -> int:
        removed = 0
        for table, key in (("batch_quarantine", "batch_id"), ("sample_quarantine", "sample_id")):
            rows = connection.execute(
                f"SELECT {key} FROM {table} WHERE purge_after <= ?", (now,)  # noqa: S608 - fixed identifiers
            ).fetchall()
            connection.execute(
                f"DELETE FROM {table} WHERE purge_after <= ?", (now,)  # noqa: S608 - fixed identifiers
            )
            for row in rows:
                self._audit(
                    connection, "QUARANTINE_PAYLOAD_EXPIRED", row[0],
                    {"cause": "EXPIRED_RETENTION", "table": table},
                )
            removed += len(rows)
        return removed

    def _audit(
        self,
        connection: sqlite3.Connection,
        event: str,
        resource_id: str | None,
        details: Mapping[str, object],
    ) -> None:
        connection.execute(
            "INSERT INTO local_audit (id, event, resource_id, details_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), event, resource_id,
                json.dumps(dict(details), sort_keys=True, separators=(",", ":")), int(self._clock()),
            ),
        )

    def counts(self) -> dict[str, int]:
        connection = self._connect()
        try:
            return {
                "queued": connection.execute("SELECT COUNT(*) FROM queued_batches").fetchone()[0],
                "batch_quarantine": connection.execute("SELECT COUNT(*) FROM batch_quarantine").fetchone()[0],
                "sample_quarantine": connection.execute("SELECT COUNT(*) FROM sample_quarantine").fetchone()[0],
                "audit": connection.execute("SELECT COUNT(*) FROM local_audit").fetchone()[0],
            }
        finally:
            connection.close()

    def journal_mode(self) -> str:
        connection = self._connect()
        try:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        finally:
            connection.close()

    def integrity_check(self) -> str:
        connection = self._connect()
        try:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()
