import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.metrics.schemas import (
    BatchDecisionInput,
    BatchRetryInput,
    BatchStatusQueryInput,
    MetricBatchInput,
    MetricReuploadInput,
)
from backend.app.metrics.service import (
    BatchDiagnostics,
    BatchReceipt,
    BatchStatusRecord,
    MetricAccessRejected,
    MetricAuditContext,
    MetricsApplication,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
BATCH_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ACTOR_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


@dataclass(frozen=True)
class AgentIdentity:
    organization_id: UUID
    device_id: UUID
    token_id: UUID = UUID(int=5)


def _reupload() -> MetricReuploadInput:
    incomplete = MetricReuploadInput.model_validate(
        {
            "payload_digest": "0" * 64,
            "samples": [
                {
                    "metric_name": "cpu.usage_percent",
                    "metric_value": 50,
                    "recorded_at": "2026-08-24T12:00:00Z",
                }
            ],
        }
    )
    return incomplete.model_copy(
        update={"payload_digest": incomplete.computed_digest()}
    )


class Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get_batch_status(self, **values):
        self.calls.append(("status", values))
        return BatchStatusRecord(BATCH_ID, "DLQ", 3, 0, "INVALID_PAYLOAD", None)

    async def get_batch_statuses(self, **values):
        self.calls.append(("statuses", values))
        return (await self.get_batch_status(**values),)

    async def authorize_retry(self, **values):
        self.calls.append(("retry", values))
        return BatchStatusRecord(BATCH_ID, "AWAITING_REUPLOAD", 0, 1, None, None)

    async def reupload_batch(self, **values):
        self.calls.append(("reupload", values))
        return BatchReceipt(BATCH_ID, "RECEIVED", False)

    async def export_diagnostics(self, **values):
        self.calls.append(("diagnostics", values))
        return BatchDiagnostics(
            BATCH_ID,
            "DLQ",
            3,
            0,
            "a" * 64,
            "INVALID_PAYLOAD",
            "Metric payload failed validation",
            datetime(2026, 8, 24, tzinfo=timezone.utc),
            None,
        )

    async def decide_exhausted_batch(self, **values):
        self.calls.append(("decision", values))
        return BatchStatusRecord(
            BATCH_ID, "DLQ_EXHAUSTED", 3, 3, "PROCESSING_ERROR", values["action"]
        )

    async def process_next_batch(self, **values):
        self.calls.append(("process", values))
        return BatchReceipt(BATCH_ID, "PROCESSED", False)


def test_rf04_schemas_are_closed_and_bounded() -> None:
    with pytest.raises(ValidationError):
        BatchStatusQueryInput(batch_ids=tuple(UUID(int=i) for i in range(51)))
    with pytest.raises(ValidationError):
        BatchRetryInput.model_validate({"reason": "short", "organization_id": str(ORG_ID)})
    with pytest.raises(ValidationError):
        BatchDecisionInput.model_validate({"action": "DELETE", "reason": "x" * 10})

    assert BatchRetryInput(reason="  authorized retry  ").reason == "authorized retry"


def test_agent_status_and_reupload_derive_composite_identity() -> None:
    repository = Repository()
    application = MetricsApplication(repository)
    identity = AgentIdentity(ORG_ID, DEVICE_ID)

    status = asyncio.run(application.get_agent_batch_status(identity, DEVICE_ID, BATCH_ID))
    receipt = asyncio.run(
        application.reupload_batch(identity, DEVICE_ID, BATCH_ID, _reupload())
    )

    assert status.batch_id == BATCH_ID
    assert receipt.status == "RECEIVED"
    assert repository.calls[0][1]["organization_id"] == ORG_ID
    assert repository.calls[1][1]["device_id"] == DEVICE_ID
    assert "organization_id" not in _reupload().model_dump()


def test_agent_status_rejects_foreign_device_before_repository() -> None:
    repository = Repository()
    application = MetricsApplication(repository)

    with pytest.raises(MetricAccessRejected):
        asyncio.run(
            application.get_agent_batch_status(
                AgentIdentity(ORG_ID, DEVICE_ID), UUID(int=99), BATCH_ID
            )
        )

    assert repository.calls == []


def test_admin_retry_and_decision_forward_audit_context() -> None:
    repository = Repository()
    application = MetricsApplication(repository)
    audit = MetricAuditContext("127.0.0.1", "pytest")

    retry = asyncio.run(
        application.authorize_retry(
            ORG_ID,
            DEVICE_ID,
            BATCH_ID,
            ACTOR_ID,
            BatchRetryInput(reason="operator approved"),
            audit,
        )
    )
    decision = asyncio.run(
        application.decide_exhausted_batch(
            ORG_ID,
            DEVICE_ID,
            BATCH_ID,
            ACTOR_ID,
            BatchDecisionInput(action="PURGE_LOCAL", reason="disk protection"),
            audit,
        )
    )

    assert retry.status == "AWAITING_REUPLOAD"
    assert decision.decision == "PURGE_LOCAL"
    assert repository.calls[0][1]["audit"] == audit
    assert repository.calls[1][1]["actor_id"] == ACTOR_ID


def test_worker_application_keeps_explicit_tenant_scope() -> None:
    repository = Repository()
    application = MetricsApplication(repository)

    receipt = asyncio.run(application.process_next_batch(ORG_ID))

    assert receipt is not None
    assert receipt.status == "PROCESSED"
    assert repository.calls == [("process", {"organization_id": ORG_ID})]
