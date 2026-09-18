import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from backend.app.metrics.schemas import MetricBatchInput, MetricSampleInput
from backend.app.metrics.service import (
    AlertRule,
    BatchDigestMismatch,
    BatchReceipt,
    MetricAccessRejected,
    MetricsApplication,
    evaluate_rule,
    next_failure_state,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
BATCH_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


class Repository:
    def __init__(self) -> None:
        self.call: dict[str, object] | None = None

    async def ingest_batch(self, **values: object) -> BatchReceipt:
        self.call = values
        return BatchReceipt(batch_id=BATCH_ID, status="RECEIVED", duplicate=False)

    async def list_telemetry(self, **_values: object):
        return ()

    async def create_alert_rule(self, **_values: object):
        raise AssertionError("not used")

    async def list_alerts(self, **_values: object):
        return ()


@dataclass(frozen=True)
class AgentIdentity:
    organization_id: UUID
    device_id: UUID


def _valid_batch() -> MetricBatchInput:
    incomplete = MetricBatchInput(
        batch_id=BATCH_ID,
        payload_digest="0" * 64,
        samples=[
            MetricSampleInput(
                metric_name="cpu.usage_percent",
                metric_value=92,
                recorded_at=datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
            )
        ],
    )
    return incomplete.model_copy(
        update={"payload_digest": incomplete.computed_digest()}
    )


def test_ingest_derives_tenant_and_device_from_authenticated_agent() -> None:
    repository = Repository()
    application = MetricsApplication(repository)
    identity = AgentIdentity(
        organization_id=ORG_ID,
        device_id=DEVICE_ID,
    )

    receipt = asyncio.run(
        application.ingest_batch(identity, DEVICE_ID, _valid_batch())
    )

    assert receipt.status == "RECEIVED"
    assert repository.call is not None
    assert repository.call["organization_id"] == ORG_ID
    assert repository.call["device_id"] == DEVICE_ID
    assert "organization_id" not in _valid_batch().model_dump()


def test_ingest_rejects_wrong_device_and_digest_before_storage() -> None:
    repository = Repository()
    application = MetricsApplication(repository)
    identity = AgentIdentity(
        organization_id=ORG_ID,
        device_id=DEVICE_ID,
    )

    with pytest.raises(MetricAccessRejected):
        asyncio.run(application.ingest_batch(identity, UUID(int=9), _valid_batch()))
    with pytest.raises(BatchDigestMismatch):
        asyncio.run(
            application.ingest_batch(
                identity,
                DEVICE_ID,
                _valid_batch().model_copy(update={"payload_digest": "f" * 64}),
            )
        )

    assert repository.call is None


def test_dlq_counter_machine_separates_worker_and_admin_cycles() -> None:
    assert next_failure_state(retry_count=0, reprocess_count=0) == (1, "RECEIVED")
    assert next_failure_state(retry_count=2, reprocess_count=0) == (3, "DLQ")
    assert next_failure_state(retry_count=2, reprocess_count=3) == (
        3,
        "DLQ_EXHAUSTED",
    )


def test_alert_rule_requires_threshold_persistence_window() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
    rule = AlertRule(
        id=UUID(int=4),
        metric_name="cpu.usage_percent",
        operator="GTE",
        threshold_value=90,
        duration_seconds=60,
        severity="CRITICAL",
    )
    recent = [(now - timedelta(seconds=30), 95.0), (now, 96.0)]
    persistent = [(now - timedelta(seconds=65), 95.0), (now, 96.0)]

    assert not evaluate_rule(rule, recent, now=now)
    assert evaluate_rule(rule, persistent, now=now)
    assert not evaluate_rule(
        replace(rule, operator="LT", threshold_value=10), persistent, now=now
    )
