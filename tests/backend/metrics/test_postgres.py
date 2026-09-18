import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.app.metrics.postgres import (
    PostgresMetricRepository,
    sanitize_processing_failure,
)
from backend.app.metrics.service import BatchIdentityCollision


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
BATCH_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


class Result:
    def __init__(self, row=None) -> None:
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.row if isinstance(self.row, list) else []


class Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.results = [
            Result(),
            Result(),
            Result({"id": BATCH_ID, "status": "RECEIVED"}),
            Result(),
        ]

    async def execute(self, statement, parameters=None):
        self.calls.append((str(statement), parameters))
        return self.results.pop(0)


class Transaction:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class Engine:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def begin(self):
        return Transaction(self.connection)


def test_ingest_sets_rls_and_binds_composite_identity() -> None:
    connection = Connection()
    repository = PostgresMetricRepository(Engine(connection))

    receipt = asyncio.run(
        repository.ingest_batch(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            batch_id=BATCH_ID,
            payload_digest="d" * 64,
            canonical_samples=[
                {
                    "metric_name": "cpu.usage_percent",
                    "metric_value": "42.5",
                    "recorded_at": "2026-08-24T12:00:00Z",
                    "labels": {},
                }
            ],
        )
    )

    assert receipt.status == "RECEIVED"
    assert connection.calls[1][1] == {"organization_id": str(ORG_ID)}
    insert_parameters = connection.calls[2][1]
    assert insert_parameters["organization_id"] == ORG_ID
    assert insert_parameters["device_id"] == DEVICE_ID
    assert insert_parameters["batch_id"] == BATCH_ID
    sql = "\n".join(statement for statement, _ in connection.calls)
    assert str(ORG_ID) not in sql
    assert str(DEVICE_ID) not in sql
    assert str(BATCH_ID) not in sql


class DuplicateConnection(Connection):
    def __init__(self, digest: str) -> None:
        super().__init__()
        self.results = [
            Result(),
            Result(),
            Result(),
            Result(
                {
                    "id": BATCH_ID,
                    "status": "PROCESSING",
                    "payload_digest": digest,
                }
            ),
        ]


def test_ingest_is_idempotent_only_when_composite_identity_digest_matches() -> None:
    digest = "d" * 64
    connection = DuplicateConnection(digest)
    repository = PostgresMetricRepository(Engine(connection))

    receipt = asyncio.run(
        repository.ingest_batch(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            batch_id=BATCH_ID,
            payload_digest=digest,
            canonical_samples=[],
        )
    )

    assert receipt.duplicate
    assert receipt.status == "PROCESSING"

    collision_repository = PostgresMetricRepository(
        Engine(DuplicateConnection("e" * 64))
    )
    with pytest.raises(BatchIdentityCollision):
        asyncio.run(
            collision_repository.ingest_batch(
                organization_id=ORG_ID,
                device_id=DEVICE_ID,
                batch_id=BATCH_ID,
                payload_digest=digest,
                canonical_samples=[],
            )
        )


class SequenceConnection(Connection):
    def __init__(self, rows: list[dict[str, object] | None]) -> None:
        super().__init__()
        self.results = [Result(row) for row in rows]


def test_processing_failure_derives_locked_counters_and_emits_exhaustion_alert() -> None:
    connection = SequenceConnection(
        [
            None,
            None,
            {"retry_count": 2, "reprocess_count": 3, "status": "PROCESSING"},
            None,
            None,
            None,
        ]
    )
    repository = PostgresMetricRepository(Engine(connection))

    result = asyncio.run(
        repository.record_processing_failure(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            batch_id=BATCH_ID,
            error_code="password=secret",
        )
    )

    assert result == "DLQ_EXHAUSTED"
    sql = "\n".join(statement for statement, _ in connection.calls)
    assert "FOR UPDATE" in sql
    assert "INSERT INTO public.alerts" in sql
    update_parameters = connection.calls[3][1]
    assert update_parameters["retry_count"] == 3
    assert update_parameters["error_code"] == "PROCESSING_ERROR"
    assert "secret" not in str(connection.calls)


def test_worker_claims_with_skip_locked_and_inserts_samples_idempotently() -> None:
    connection = SequenceConnection(
        [
            None,
            None,
            {
                "id": BATCH_ID,
                "device_id": DEVICE_ID,
                "payload_json": [
                    {
                        "metric_name": "cpu.usage_percent",
                        "metric_value": "42.5",
                        "recorded_at": "2026-08-24T12:00:00Z",
                        "labels": {},
                    }
                ],
            },
            None,
            None,
            None,
            {"status": "PROCESSING"},
            None,
            None,
        ]
    )
    repository = PostgresMetricRepository(Engine(connection))

    receipt = asyncio.run(repository.process_next_batch(organization_id=ORG_ID))

    assert receipt is not None
    assert receipt.status == "PROCESSED"
    sql = "\n".join(statement for statement, _ in connection.calls)
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "ON CONFLICT (organization_id, id, recorded_at) DO NOTHING" in sql
    assert "status = 'PROCESSED'" in sql


def test_failure_sanitizer_never_persists_untrusted_exception_text() -> None:
    assert sanitize_processing_failure("password=secret") == (
        "PROCESSING_ERROR",
        "Metric processing failed",
    )


def test_telemetry_query_enforces_actor_assignment_when_scoped() -> None:
    actor_id = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    connection = SequenceConnection([None, None, []])
    repository = PostgresMetricRepository(Engine(connection))

    result = asyncio.run(
        repository.list_telemetry(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            actor_id=actor_id,
            assigned_only=True,
            metric_name=None,
            limit=10,
        )
    )

    assert result == ()
    sql, parameters = connection.calls[2]
    assert "FROM public.device_assignments" in sql
    assert parameters["actor_id"] == actor_id
    assert parameters["assigned_only"] is True
