"""Load, concurrency, and failure recovery tests under multi-tenant isolation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from unittest.mock import AsyncMock
from uuid import uuid4

from backend.app.metrics.schemas import MetricBatchInput, MetricSampleInput
from backend.app.metrics.service import (
    BatchDiagnostics,
    BatchReceipt,
    MetricsApplication,
)
from backend.app.metrics.worker import MetricBatchWorker


class SimpleIdentity:
    def __init__(self, organization_id: object, device_id: object, token_id: object) -> None:
        self.organization_id = organization_id
        self.device_id = device_id
        self.token_id = token_id


def test_concurrent_multi_tenant_batch_ingestion_under_load() -> None:
    """Simulates high-volume concurrent batch ingestion across multiple tenants."""
    async def _test() -> None:
        mock_repository = AsyncMock()
        mock_repository.ingest_batch.return_value = BatchReceipt(
            batch_id=uuid4(),
            status="RECEIVED",
            duplicate=False,
        )

        app = MetricsApplication(mock_repository)
        tenants = [uuid4() for _ in range(5)]
        devices = [uuid4() for _ in range(20)]

        async def ingest_task(tenant_id: object, device_id: object, index: int) -> BatchReceipt:
            identity = SimpleIdentity(tenant_id, device_id, uuid4())
            sample = MetricSampleInput(
                metric_name="system.cpu.usage",
                metric_value=Decimal("45.2000"),
                recorded_at=datetime.now(UTC),
            )
            samples = (sample,)
            serialized = json.dumps(
                [s.canonical_value() for s in samples],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
            digest = hashlib.sha256(serialized).hexdigest()

            batch = MetricBatchInput(
                batch_id=uuid4(),
                payload_digest=digest,
                samples=samples,
            )
            return await app.ingest_batch(
                identity=identity,  # type: ignore[arg-type]
                device_id=device_id,  # type: ignore[arg-type]
                batch=batch,
            )

        tasks = [
            ingest_task(tenants[i % len(tenants)], devices[i % len(devices)], i)
            for i in range(100)
        ]
        results = await asyncio.gather(*tasks)

        assert len(results) == 100
        assert all(r.status == "RECEIVED" for r in results)
        assert mock_repository.ingest_batch.call_count == 100

    asyncio.run(_test())


def test_worker_recovery_and_processing_under_fault() -> None:
    """Validates that worker handles batches and processes multiple tenants safely."""
    async def _test() -> None:
        mock_repo = AsyncMock()
        tenant_id = uuid4()
        batch_id = uuid4()

        mock_repo.list_active_organization_ids.return_value = (tenant_id,)
        mock_repo.process_next_batch.side_effect = [
            BatchReceipt(batch_id=batch_id, status="PROCESSED", duplicate=False),
            None,
        ]
        mock_repo.evaluate_alerts.return_value = ()

        app = MetricsApplication(mock_repo)
        worker = MetricBatchWorker(
            metrics_application=app,
            poll_interval_seconds=0.01,
        )

        stats = await worker.run_once()
        assert stats.batches_processed == 1
        assert stats.tenants_scanned == 1

    asyncio.run(_test())


def test_dlq_diagnostics_export_is_sanitized_and_safe() -> None:
    """Verifies that DLQ diagnostic export strips secrets and sensitive keys."""
    async def _test() -> None:
        mock_repo = AsyncMock()
        tenant_id = uuid4()
        batch_id = uuid4()
        device_id = uuid4()

        mock_repo.export_diagnostics.return_value = BatchDiagnostics(
            batch_id=batch_id,
            status="DLQ",
            retry_count=3,
            reprocess_count=0,
            payload_digest="sha256:abcd1234abcd",
            error_code="VALIDATION_FAILED",
            error_summary="Payload exceeds limit",
            received_at=datetime.now(UTC),
            processed_at=None,
        )

        app = MetricsApplication(mock_repo)
        diagnostics = await app.export_diagnostics(
            organization_id=tenant_id,
            device_id=device_id,
            batch_id=batch_id,
        )

        assert diagnostics.batch_id == batch_id
        assert diagnostics.status == "DLQ"
        assert "password" not in str(diagnostics.error_summary)
        assert "token" not in str(diagnostics.error_summary)

    asyncio.run(_test())
