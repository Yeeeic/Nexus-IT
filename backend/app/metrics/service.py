"""Application contracts for metrics, telemetry, DLQ, and alerts."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hmac
from typing import Literal, Protocol
from uuid import UUID

from backend.app.metrics.schemas import (
    AlertRuleInput,
    AlertSeverity,
    BatchDecisionInput,
    BatchRetryInput,
    ComparisonOperator,
    MetricBatchInput,
    MetricReuploadInput,
)


BatchStatus = Literal[
    "RECEIVED",
    "PROCESSING",
    "PROCESSED",
    "DLQ",
    "AWAITING_REUPLOAD",
    "DLQ_EXHAUSTED",
]


class MetricAccessRejected(Exception):
    pass


class BatchDigestMismatch(Exception):
    pass


class BatchIdentityCollision(Exception):
    pass


class MetricsUnavailable(Exception):
    pass


class BatchNotFound(Exception):
    pass


class BatchStateRejected(Exception):
    pass


class BatchDecisionConflict(Exception):
    pass


class AgentMetricIdentity(Protocol):
    """Structural boundary compatible with any authenticated agent module."""

    organization_id: UUID
    device_id: UUID
    token_id: UUID


class AgentMetricAuthenticator(Protocol):
    async def authenticate(self, token: str) -> AgentMetricIdentity: ...


@dataclass(frozen=True, slots=True)
class BatchReceipt:
    batch_id: UUID
    status: BatchStatus
    duplicate: bool


BatchDecision = Literal["PURGE_LOCAL", "RETAIN"]


@dataclass(frozen=True, slots=True)
class BatchStatusRecord:
    batch_id: UUID
    status: BatchStatus
    retry_count: int
    reprocess_count: int
    error_code: str | None
    decision: BatchDecision | None


@dataclass(frozen=True, slots=True)
class BatchDiagnostics:
    batch_id: UUID
    status: BatchStatus
    retry_count: int
    reprocess_count: int
    payload_digest: str
    error_code: str | None
    error_summary: str | None
    received_at: datetime
    processed_at: datetime | None


@dataclass(frozen=True, slots=True)
class MetricAuditContext:
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    id: UUID
    device_id: UUID
    metric_name: str
    metric_value: float
    recorded_at: datetime
    labels: dict[str, str]


@dataclass(frozen=True, slots=True)
class AlertRule:
    id: UUID
    metric_name: str
    operator: ComparisonOperator
    threshold_value: Decimal | float | int
    duration_seconds: int
    severity: AlertSeverity


@dataclass(frozen=True, slots=True)
class AlertRuleRecord(AlertRule):
    name: str
    is_enabled: bool
    created_at: datetime


AlertStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"]


@dataclass(frozen=True, slots=True)
class AlertSummary:
    id: UUID
    device_id: UUID
    alert_rule_id: UUID | None
    severity: AlertSeverity
    status: AlertStatus
    message: str
    triggered_at: datetime
    resolved_at: datetime | None


class MetricRepository(Protocol):
    async def ingest_batch(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        payload_digest: str,
        canonical_samples: list[dict[str, object]],
    ) -> BatchReceipt: ...

    async def list_telemetry(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        assigned_only: bool,
        metric_name: str | None,
        limit: int,
    ) -> tuple[TelemetrySample, ...]: ...

    async def create_alert_rule(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        rule: AlertRuleInput,
    ) -> AlertRuleRecord: ...

    async def list_alert_rules(
        self,
        *,
        organization_id: UUID,
    ) -> tuple[AlertRuleRecord, ...]: ...

    async def list_alerts(
        self,
        *,
        organization_id: UUID,
        limit: int,
    ) -> tuple[AlertSummary, ...]: ...

    async def get_batch_status(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
    ) -> BatchStatusRecord: ...

    async def get_batch_statuses(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_ids: tuple[UUID, ...],
    ) -> tuple[BatchStatusRecord, ...]: ...

    async def authorize_retry(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        actor_id: UUID,
        reason: str,
        audit: MetricAuditContext,
    ) -> BatchStatusRecord: ...

    async def reupload_batch(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        payload_digest: str,
        canonical_samples: list[dict[str, object]],
    ) -> BatchReceipt: ...

    async def export_diagnostics(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
    ) -> BatchDiagnostics: ...

    async def decide_exhausted_batch(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        actor_id: UUID,
        action: BatchDecision,
        reason: str,
        audit: MetricAuditContext,
    ) -> BatchStatusRecord: ...

    async def process_next_batch(
        self,
        *,
        organization_id: UUID,
    ) -> BatchReceipt | None: ...

    async def list_active_organization_ids(self) -> tuple[UUID, ...]: ...

    async def evaluate_alerts(
        self,
        *,
        organization_id: UUID,
        now: datetime | None = None,
    ) -> tuple[AlertSummary, ...]: ...


class MetricsApplication:
    def __init__(self, repository: MetricRepository) -> None:
        self._repository = repository

    async def ingest_batch(
        self,
        identity: AgentMetricIdentity,
        device_id: UUID,
        batch: MetricBatchInput,
    ) -> BatchReceipt:
        if identity.device_id != device_id:
            raise MetricAccessRejected
        if not hmac.compare_digest(batch.payload_digest, batch.computed_digest()):
            raise BatchDigestMismatch
        try:
            return await self._repository.ingest_batch(
                organization_id=identity.organization_id,
                device_id=identity.device_id,
                batch_id=batch.batch_id,
                payload_digest=batch.payload_digest,
                canonical_samples=batch.canonical_samples(),
            )
        except (BatchIdentityCollision,):
            raise
        except Exception:
            raise MetricsUnavailable from None

    async def list_telemetry(
        self,
        organization_id: UUID,
        device_id: UUID,
        *,
        actor_id: UUID,
        assigned_only: bool,
        metric_name: str | None,
        limit: int,
    ) -> tuple[TelemetrySample, ...]:
        try:
            return await self._repository.list_telemetry(
                organization_id=organization_id,
                device_id=device_id,
                actor_id=actor_id,
                assigned_only=assigned_only,
                metric_name=metric_name,
                limit=limit,
            )
        except Exception:
            raise MetricsUnavailable from None

    async def create_alert_rule(
        self,
        organization_id: UUID,
        actor_id: UUID,
        rule: AlertRuleInput,
    ) -> AlertRuleRecord:
        try:
            return await self._repository.create_alert_rule(
                organization_id=organization_id,
                actor_id=actor_id,
                rule=rule,
            )
        except Exception:
            raise MetricsUnavailable from None

    async def list_alert_rules(
        self,
        organization_id: UUID,
    ) -> tuple[AlertRuleRecord, ...]:
        try:
            return await self._repository.list_alert_rules(
                organization_id=organization_id,
            )
        except Exception:
            raise MetricsUnavailable from None

    async def list_alerts(
        self,
        organization_id: UUID,
        *,
        limit: int,
    ) -> tuple[AlertSummary, ...]:
        try:
            return await self._repository.list_alerts(
                organization_id=organization_id,
                limit=limit,
            )
        except Exception:
            raise MetricsUnavailable from None

    @staticmethod
    def _require_own_device(identity: AgentMetricIdentity, device_id: UUID) -> None:
        if identity.device_id != device_id:
            raise MetricAccessRejected

    async def get_agent_batch_status(
        self,
        identity: AgentMetricIdentity,
        device_id: UUID,
        batch_id: UUID,
    ) -> BatchStatusRecord:
        self._require_own_device(identity, device_id)
        try:
            return await self._repository.get_batch_status(
                organization_id=identity.organization_id,
                device_id=device_id,
                batch_id=batch_id,
            )
        except BatchNotFound:
            raise
        except Exception:
            raise MetricsUnavailable from None

    async def get_agent_batch_statuses(
        self,
        identity: AgentMetricIdentity,
        device_id: UUID,
        batch_ids: tuple[UUID, ...],
    ) -> tuple[BatchStatusRecord, ...]:
        self._require_own_device(identity, device_id)
        try:
            return await self._repository.get_batch_statuses(
                organization_id=identity.organization_id,
                device_id=device_id,
                batch_ids=batch_ids,
            )
        except Exception:
            raise MetricsUnavailable from None

    async def authorize_retry(
        self,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        actor_id: UUID,
        retry: BatchRetryInput,
        audit: MetricAuditContext,
    ) -> BatchStatusRecord:
        try:
            return await self._repository.authorize_retry(
                organization_id=organization_id,
                device_id=device_id,
                batch_id=batch_id,
                actor_id=actor_id,
                reason=retry.reason,
                audit=audit,
            )
        except (BatchNotFound, BatchStateRejected):
            raise
        except Exception:
            raise MetricsUnavailable from None

    async def reupload_batch(
        self,
        identity: AgentMetricIdentity,
        device_id: UUID,
        batch_id: UUID,
        payload: MetricReuploadInput,
    ) -> BatchReceipt:
        self._require_own_device(identity, device_id)
        if not hmac.compare_digest(payload.payload_digest, payload.computed_digest()):
            raise BatchDigestMismatch
        try:
            return await self._repository.reupload_batch(
                organization_id=identity.organization_id,
                device_id=device_id,
                batch_id=batch_id,
                payload_digest=payload.payload_digest,
                canonical_samples=payload.canonical_samples(),
            )
        except (BatchIdentityCollision, BatchNotFound, BatchStateRejected):
            raise
        except Exception:
            raise MetricsUnavailable from None

    async def export_diagnostics(
        self,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
    ) -> BatchDiagnostics:
        try:
            return await self._repository.export_diagnostics(
                organization_id=organization_id,
                device_id=device_id,
                batch_id=batch_id,
            )
        except BatchNotFound:
            raise
        except Exception:
            raise MetricsUnavailable from None

    async def decide_exhausted_batch(
        self,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        actor_id: UUID,
        decision: BatchDecisionInput,
        audit: MetricAuditContext,
    ) -> BatchStatusRecord:
        try:
            return await self._repository.decide_exhausted_batch(
                organization_id=organization_id,
                device_id=device_id,
                batch_id=batch_id,
                actor_id=actor_id,
                action=decision.action,
                reason=decision.reason,
                audit=audit,
            )
        except (BatchDecisionConflict, BatchNotFound, BatchStateRejected):
            raise
        except Exception:
            raise MetricsUnavailable from None

    async def process_next_batch(
        self,
        organization_id: UUID,
    ) -> BatchReceipt | None:
        try:
            return await self._repository.process_next_batch(
                organization_id=organization_id,
            )
        except (BatchNotFound, BatchStateRejected):
            raise
        except Exception:
            raise MetricsUnavailable from None

    async def list_active_organization_ids(self) -> tuple[UUID, ...]:
        try:
            return await self._repository.list_active_organization_ids()
        except Exception:
            raise MetricsUnavailable from None

    async def evaluate_alerts(
        self,
        organization_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[AlertSummary, ...]:
        try:
            return await self._repository.evaluate_alerts(
                organization_id=organization_id,
                now=now,
            )
        except Exception:
            raise MetricsUnavailable from None


def next_failure_state(
    *, retry_count: int, reprocess_count: int
) -> tuple[int, BatchStatus]:
    next_retry = min(retry_count + 1, 3)
    if next_retry < 3:
        return next_retry, "RECEIVED"
    if reprocess_count >= 3:
        return next_retry, "DLQ_EXHAUSTED"
    return next_retry, "DLQ"


def _compare(operator: ComparisonOperator, value: float, threshold: float) -> bool:
    if operator == "GT":
        return value > threshold
    if operator == "GTE":
        return value >= threshold
    if operator == "LT":
        return value < threshold
    if operator == "LTE":
        return value <= threshold
    return value == threshold


def evaluate_rule(
    rule: AlertRule,
    samples: Sequence[tuple[datetime, float]],
    *,
    now: datetime,
) -> bool:
    if not samples:
        return False
    ordered = sorted(samples, key=lambda item: item[0])
    threshold = float(rule.threshold_value)
    latest_at, latest_value = ordered[-1]
    if latest_at > now or not _compare(rule.operator, latest_value, threshold):
        return False
    boundary = now - timedelta(seconds=rule.duration_seconds)
    qualifying_start = latest_at
    for recorded_at, value in reversed(ordered):
        if recorded_at > now:
            continue
        if not _compare(rule.operator, value, threshold):
            break
        qualifying_start = recorded_at
    return qualifying_start <= boundary
