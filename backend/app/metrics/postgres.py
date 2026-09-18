from datetime import UTC, datetime, timedelta
import hmac
import json
from typing import cast
from uuid import UUID, uuid4, uuid5

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.metrics.schemas import AlertRuleInput, MetricSampleInput
from backend.app.metrics.service import (
    AlertRule,
    AlertRuleRecord,
    AlertSummary,
    BatchDecision,
    BatchDecisionConflict,
    BatchDiagnostics,
    BatchIdentityCollision,
    BatchNotFound,
    BatchReceipt,
    BatchStateRejected,
    BatchStatus,
    BatchStatusRecord,
    MetricAuditContext,
    TelemetrySample,
    evaluate_rule,
    next_failure_state,
)


_PROCESSING_FAILURES = {
    "INVALID_PAYLOAD": "Metric payload failed validation",
    "STORAGE_ERROR": "Metric storage failed",
    "PROCESSING_ERROR": "Metric processing failed",
}


def sanitize_processing_failure(error_code: str) -> tuple[str, str]:
    safe_code = error_code if error_code in _PROCESSING_FAILURES else "PROCESSING_ERROR"
    return safe_code, _PROCESSING_FAILURES[safe_code]


class PostgresMetricRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @staticmethod
    async def _set_tenant(connection: object, organization_id: UUID) -> None:
        await connection.execute(text("SET LOCAL ROLE nexus_app_user"))
        await connection.execute(
            text(
                "SELECT set_config("
                "'app.current_organization_id', :organization_id, true)"
            ),
            {"organization_id": str(organization_id)},
        )

    @staticmethod
    def _status_record(row: object) -> BatchStatusRecord:
        return BatchStatusRecord(
            batch_id=row["id"],
            status=cast(BatchStatus, row["status"]),
            retry_count=row["retry_count"],
            reprocess_count=row["reprocess_count"],
            error_code=row["error_code"],
            decision=cast(BatchDecision | None, row.get("decision")),
        )

    @staticmethod
    async def _append_audit(
        connection: object,
        *,
        organization_id: UUID,
        actor_id: UUID | None,
        actor_type: str,
        action: str,
        batch_id: UUID,
        status: str,
        details: dict[str, object],
        audit: MetricAuditContext | None = None,
    ) -> None:
        await connection.execute(
            text(
                """
                INSERT INTO public.audit_logs (
                    id, organization_id, actor_id, actor_type, ip_address,
                    user_agent, action, resource_type, resource_id, status,
                    details
                ) VALUES (
                    :id, :organization_id, :actor_id, :actor_type,
                    CAST(:ip_address AS inet), :user_agent, :action,
                    'metric_batch', :batch_id, :status,
                    CAST(:details AS jsonb)
                )
                """
            ),
            {
                "id": uuid4(),
                "organization_id": organization_id,
                "actor_id": actor_id,
                "actor_type": actor_type,
                "ip_address": audit.ip_address if audit else None,
                "user_agent": (
                    (audit.user_agent or "").strip()[:255] or None if audit else None
                ),
                "action": action,
                "batch_id": batch_id,
                "status": status,
                "details": json.dumps(details, separators=(",", ":")),
            },
        )

    async def ingest_batch(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        payload_digest: str,
        canonical_samples: list[dict[str, object]],
    ) -> BatchReceipt:
        payload_json = json.dumps(
            canonical_samples,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        duplicate = False
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    INSERT INTO public.metric_batches (
                        organization_id, device_id, id, status, sample_count,
                        retry_count, reprocess_count, payload_digest, payload_json
                    ) VALUES (
                        :organization_id, :device_id, :batch_id, 'RECEIVED',
                        :sample_count, 0, 0, :payload_digest,
                        CAST(:payload_json AS jsonb)
                    )
                    ON CONFLICT (organization_id, device_id, id) DO NOTHING
                    RETURNING id, status, payload_digest
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_id": batch_id,
                    "sample_count": len(canonical_samples),
                    "payload_digest": payload_digest,
                    "payload_json": payload_json,
                },
            )
            row = result.mappings().first()
            if row is None:
                duplicate = True
                existing = await connection.execute(
                    text(
                        """
                        SELECT id, status, payload_digest
                        FROM public.metric_batches
                        WHERE organization_id = :organization_id
                          AND device_id = :device_id
                          AND id = :batch_id
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "device_id": device_id,
                        "batch_id": batch_id,
                    },
                )
                row = existing.mappings().first()
                if row is None or not hmac.compare_digest(
                    row["payload_digest"], payload_digest
                ):
                    raise BatchIdentityCollision
            else:
                now_utc = datetime.now(UTC)
                await connection.execute(
                    text(
                        """
                        UPDATE public.devices
                        SET last_seen_at = :last_seen_at,
                            updated_at = GREATEST(updated_at, :last_seen_at)
                        WHERE organization_id = :organization_id
                          AND id = :device_id
                          AND is_active
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "device_id": device_id,
                        "last_seen_at": now_utc,
                    },
                )
            receipt = BatchReceipt(
                batch_id=row["id"],
                status=cast(BatchStatus, row["status"]),
                duplicate=duplicate,
            )
        return receipt

    async def get_batch_status(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
    ) -> BatchStatusRecord:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT batch.id, batch.status, batch.retry_count,
                           batch.reprocess_count, batch.error_code,
                           (
                               SELECT audit.details ->> 'action'
                               FROM public.audit_logs AS audit
                               WHERE audit.organization_id = batch.organization_id
                                 AND audit.resource_id = batch.id
                                 AND audit.action = 'METRIC_BATCH.DECISION'
                               ORDER BY audit.created_at DESC
                               LIMIT 1
                           ) AS decision
                    FROM public.metric_batches AS batch
                    WHERE batch.organization_id = :organization_id
                      AND batch.device_id = :device_id
                      AND batch.id = :batch_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_id": batch_id,
                },
            )
            row = result.mappings().first()
        if row is None:
            raise BatchNotFound
        return self._status_record(row)

    async def get_batch_statuses(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_ids: tuple[UUID, ...],
    ) -> tuple[BatchStatusRecord, ...]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT batch.id, batch.status, batch.retry_count,
                           batch.reprocess_count, batch.error_code,
                           (
                               SELECT audit.details ->> 'action'
                               FROM public.audit_logs AS audit
                               WHERE audit.organization_id = batch.organization_id
                                 AND audit.resource_id = batch.id
                                 AND audit.action = 'METRIC_BATCH.DECISION'
                               ORDER BY audit.created_at DESC
                               LIMIT 1
                           ) AS decision
                    FROM public.metric_batches AS batch
                    WHERE batch.organization_id = :organization_id
                      AND batch.device_id = :device_id
                      AND batch.id = ANY(CAST(:batch_ids AS uuid[]))
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_ids": list(batch_ids),
                },
            )
            rows = result.mappings().all()
        return tuple(self._status_record(row) for row in rows)

    async def authorize_retry(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        actor_id: UUID,
        reason: str,
        audit: MetricAuditContext,
    ) -> BatchStatusRecord:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, status, retry_count, reprocess_count, error_code
                    FROM public.metric_batches
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :batch_id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_id": batch_id,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise BatchNotFound
            if row["status"] == "AWAITING_REUPLOAD":
                return self._status_record({**row, "decision": None})
            if row["status"] != "DLQ" or row["reprocess_count"] >= 3:
                raise BatchStateRejected
            updated = await connection.execute(
                text(
                    """
                    UPDATE public.metric_batches
                    SET status = 'AWAITING_REUPLOAD', retry_count = 0,
                        reprocess_count = reprocess_count + 1
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :batch_id
                    RETURNING id, status, retry_count, reprocess_count,
                              error_code
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_id": batch_id,
                },
            )
            updated_row = updated.mappings().first()
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                actor_type="USER",
                action="METRIC_BATCH.RETRY",
                batch_id=batch_id,
                status="SUCCESS",
                details={"reason": reason},
                audit=audit,
            )
        return self._status_record({**updated_row, "decision": None})

    async def reupload_batch(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        payload_digest: str,
        canonical_samples: list[dict[str, object]],
    ) -> BatchReceipt:
        payload_json = json.dumps(
            canonical_samples,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        collision = False
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, status, payload_digest
                    FROM public.metric_batches
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :batch_id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_id": batch_id,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise BatchNotFound
            if not hmac.compare_digest(row["payload_digest"], payload_digest):
                await self._append_audit(
                    connection,
                    organization_id=organization_id,
                    actor_id=device_id,
                    actor_type="AGENT",
                    action="METRIC_BATCH.REUPLOAD_COLLISION",
                    batch_id=batch_id,
                    status="DENIED",
                    details={"error_code": "COLLISION_BATCH_DIGEST_MISMATCH"},
                )
                collision = True
            elif row["status"] != "AWAITING_REUPLOAD":
                raise BatchStateRejected
            else:
                await connection.execute(
                    text(
                        """
                        UPDATE public.metric_batches
                        SET status = 'RECEIVED', retry_count = 0,
                            sample_count = :sample_count,
                            payload_json = CAST(:payload_json AS jsonb),
                            error_code = NULL, error_summary = NULL
                        WHERE organization_id = :organization_id
                          AND device_id = :device_id
                          AND id = :batch_id
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "device_id": device_id,
                        "batch_id": batch_id,
                        "sample_count": len(canonical_samples),
                        "payload_json": payload_json,
                    },
                )
        if collision:
            raise BatchIdentityCollision
        return BatchReceipt(batch_id=batch_id, status="RECEIVED", duplicate=False)

    async def export_diagnostics(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
    ) -> BatchDiagnostics:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, status, retry_count, reprocess_count,
                           payload_digest, error_code, error_summary,
                           received_at, processed_at
                    FROM public.metric_batches
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :batch_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_id": batch_id,
                },
            )
            row = result.mappings().first()
        if row is None:
            raise BatchNotFound
        return BatchDiagnostics(
            batch_id=row["id"],
            status=cast(BatchStatus, row["status"]),
            retry_count=row["retry_count"],
            reprocess_count=row["reprocess_count"],
            payload_digest=row["payload_digest"],
            error_code=row["error_code"],
            error_summary=row["error_summary"],
            received_at=row["received_at"],
            processed_at=row["processed_at"],
        )

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
    ) -> BatchStatusRecord:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT batch.id, batch.status, batch.retry_count,
                           batch.reprocess_count, batch.error_code,
                           (
                               SELECT audit.details ->> 'action'
                               FROM public.audit_logs AS audit
                               WHERE audit.organization_id = batch.organization_id
                                 AND audit.resource_id = batch.id
                                 AND audit.action = 'METRIC_BATCH.DECISION'
                               ORDER BY audit.created_at DESC
                               LIMIT 1
                           ) AS decision
                    FROM public.metric_batches AS batch
                    WHERE batch.organization_id = :organization_id
                      AND batch.device_id = :device_id
                      AND batch.id = :batch_id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_id": batch_id,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise BatchNotFound
            if row["status"] != "DLQ_EXHAUSTED":
                raise BatchStateRejected
            previous = row["decision"]
            if previous == action:
                return self._status_record(row)
            if previous == "PURGE_LOCAL" and action == "RETAIN":
                raise BatchDecisionConflict
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                actor_type="USER",
                action="METRIC_BATCH.DECISION",
                batch_id=batch_id,
                status="SUCCESS",
                details={"action": action, "reason": reason},
                audit=audit,
            )
        return self._status_record({**row, "decision": action})

    async def list_telemetry(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        assigned_only: bool,
        metric_name: str | None,
        limit: int,
    ) -> tuple[TelemetrySample, ...]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, device_id, metric_name, metric_value,
                           recorded_at, labels
                    FROM public.metric_samples
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND (
                          NOT :assigned_only OR EXISTS (
                              SELECT 1
                              FROM public.device_assignments AS assignment
                              WHERE assignment.organization_id = metric_samples.organization_id
                                AND assignment.device_id = metric_samples.device_id
                                AND assignment.user_id = :actor_id
                          )
                      )
                      AND (CAST(:metric_name AS text) IS NULL OR metric_name = CAST(:metric_name AS text))
                    ORDER BY recorded_at DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "actor_id": actor_id,
                    "assigned_only": assigned_only,
                    "metric_name": metric_name,
                    "limit": limit,
                },
            )
            rows = result.mappings().all()
        return tuple(
            TelemetrySample(
                id=row["id"],
                device_id=row["device_id"],
                metric_name=row["metric_name"],
                metric_value=float(row["metric_value"]),
                recorded_at=row["recorded_at"],
                labels=dict(row["labels"] or {}),
            )
            for row in rows
        )

    async def create_alert_rule(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        rule: AlertRuleInput,
    ) -> AlertRuleRecord:
        rule_id = uuid4()
        audit_id = uuid4()
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    INSERT INTO public.alert_rules (
                        organization_id, id, name, metric_name, operator,
                        threshold_value, duration_seconds, severity, is_enabled
                    ) VALUES (
                        :organization_id, :rule_id, :name, :metric_name,
                        :operator, :threshold_value, :duration_seconds,
                        :severity, true
                    )
                    RETURNING id, name, metric_name, operator, threshold_value,
                              duration_seconds, severity, is_enabled, created_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "rule_id": rule_id,
                    "name": rule.name,
                    "metric_name": rule.metric_name,
                    "operator": rule.operator,
                    "threshold_value": rule.threshold_value,
                    "duration_seconds": rule.duration_seconds,
                    "severity": rule.severity,
                },
            )
            row = result.mappings().first()
            await connection.execute(
                text(
                    """
                    INSERT INTO public.audit_logs (
                        id, organization_id, actor_id, actor_type, action,
                        resource_type, resource_id, status, details
                    ) VALUES (
                        :audit_id, :organization_id, :actor_id, 'USER',
                        'ALERT_RULE.CREATE', 'alert_rule', :rule_id,
                        'SUCCESS', '{}'::jsonb
                    )
                    """
                ),
                {
                    "audit_id": audit_id,
                    "organization_id": organization_id,
                    "actor_id": actor_id,
                    "rule_id": rule_id,
                },
            )
        return AlertRuleRecord(
            id=row["id"],
            name=row["name"],
            metric_name=row["metric_name"],
            operator=row["operator"],
            threshold_value=row["threshold_value"],
            duration_seconds=row["duration_seconds"],
            severity=row["severity"],
            is_enabled=row["is_enabled"],
            created_at=row["created_at"],
        )

    async def list_alert_rules(
        self,
        *,
        organization_id: UUID,
    ) -> tuple[AlertRuleRecord, ...]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, name, metric_name, operator, threshold_value,
                           duration_seconds, severity, is_enabled, created_at
                    FROM public.alert_rules
                    ORDER BY created_at DESC
                    """
                )
            )
            rows = result.mappings().all()
        return tuple(
            AlertRuleRecord(
                id=row["id"],
                name=row["name"],
                metric_name=row["metric_name"],
                operator=row["operator"],
                threshold_value=row["threshold_value"],
                duration_seconds=row["duration_seconds"],
                severity=row["severity"],
                is_enabled=row["is_enabled"],
                created_at=row["created_at"],
            )
            for row in rows
        )

    async def list_alerts(
        self,
        *,
        organization_id: UUID,
        limit: int,
    ) -> tuple[AlertSummary, ...]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, device_id, alert_rule_id, severity, status,
                           message, triggered_at, resolved_at
                    FROM public.alerts
                    WHERE organization_id = :organization_id
                    ORDER BY triggered_at DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"organization_id": organization_id, "limit": limit},
            )
            rows = result.mappings().all()
        return tuple(
            AlertSummary(
                id=row["id"],
                device_id=row["device_id"],
                alert_rule_id=row["alert_rule_id"],
                severity=row["severity"],
                status=row["status"],
                message=row["message"],
                triggered_at=row["triggered_at"],
                resolved_at=row["resolved_at"],
            )
            for row in rows
        )

    async def process_next_batch(
        self,
        *,
        organization_id: UUID,
    ) -> BatchReceipt | None:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, device_id, payload_json
                    FROM public.metric_batches
                    WHERE organization_id = :organization_id
                      AND status = 'RECEIVED'
                    ORDER BY received_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                ),
                {"organization_id": organization_id},
            )
            claimed = result.mappings().first()
            if claimed is None:
                return None
            await connection.execute(
                text(
                    """
                    UPDATE public.metric_batches
                    SET status = 'PROCESSING'
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :batch_id
                      AND status = 'RECEIVED'
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": claimed["device_id"],
                    "batch_id": claimed["id"],
                },
            )

        batch_id = claimed["id"]
        device_id = claimed["device_id"]
        try:
            raw_samples = claimed["payload_json"]
            if not isinstance(raw_samples, list) or not raw_samples:
                raise ValueError("invalid stored metric payload")
            samples = tuple(
                MetricSampleInput.model_validate(sample) for sample in raw_samples
            )
        except (ValidationError, TypeError, ValueError):
            status = await self.record_processing_failure(
                organization_id=organization_id,
                device_id=device_id,
                batch_id=batch_id,
                error_code="INVALID_PAYLOAD",
            )
            return BatchReceipt(batch_id=batch_id, status=status, duplicate=False)

        try:
            async with self._engine.begin() as connection:
                await self._set_tenant(connection, organization_id)
                locked_result = await connection.execute(
                    text(
                        """
                        SELECT status
                        FROM public.metric_batches
                        WHERE organization_id = :organization_id
                          AND device_id = :device_id
                          AND id = :batch_id
                        FOR UPDATE
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "device_id": device_id,
                        "batch_id": batch_id,
                    },
                )
                locked = locked_result.mappings().first()
                if locked is None:
                    raise BatchNotFound
                if locked["status"] != "PROCESSING":
                    raise BatchStateRejected
                sample_values = [
                    {
                        "organization_id": organization_id,
                        "id": uuid5(batch_id, str(index)),
                        "device_id": device_id,
                        "metric_name": sample.metric_name,
                        "metric_value": sample.metric_value,
                        "labels": json.dumps(sample.labels, separators=(",", ":")),
                        "recorded_at": sample.recorded_at,
                    }
                    for index, sample in enumerate(samples)
                ]
                await connection.execute(
                    text(
                        """
                        INSERT INTO public.metric_samples (
                            organization_id, id, device_id, metric_name,
                            metric_value, labels, recorded_at
                        ) VALUES (
                            :organization_id, :id, :device_id, :metric_name,
                            :metric_value, CAST(:labels AS jsonb), :recorded_at
                        )
                        ON CONFLICT (organization_id, id, recorded_at) DO NOTHING
                        """
                    ),
                    sample_values,
                )
                await connection.execute(
                    text(
                        """
                        UPDATE public.metric_batches
                        SET status = 'PROCESSED', payload_json = NULL,
                            error_code = NULL, error_summary = NULL,
                            processed_at = CURRENT_TIMESTAMP
                        WHERE organization_id = :organization_id
                          AND device_id = :device_id
                          AND id = :batch_id
                          AND status = 'PROCESSING'
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "device_id": device_id,
                        "batch_id": batch_id,
                    },
                )
        except (BatchNotFound, BatchStateRejected):
            raise
        except Exception:
            status = await self.record_processing_failure(
                organization_id=organization_id,
                device_id=device_id,
                batch_id=batch_id,
                error_code="STORAGE_ERROR",
            )
            return BatchReceipt(batch_id=batch_id, status=status, duplicate=False)
        return BatchReceipt(batch_id=batch_id, status="PROCESSED", duplicate=False)

    async def record_processing_failure(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        error_code: str,
    ) -> BatchStatus:
        error_code, error_summary = sanitize_processing_failure(error_code)
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT retry_count, reprocess_count, status
                    FROM public.metric_batches
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :batch_id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_id": batch_id,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise BatchNotFound
            if row["status"] != "PROCESSING":
                raise BatchStateRejected
            next_retry, status = next_failure_state(
                retry_count=row["retry_count"],
                reprocess_count=row["reprocess_count"],
            )
            await connection.execute(
                text(
                    """
                    UPDATE public.metric_batches
                    SET status = :status,
                        retry_count = :retry_count,
                        error_code = :error_code,
                        error_summary = :error_summary,
                        payload_json = CASE
                            WHEN :status IN ('DLQ', 'DLQ_EXHAUSTED') THEN NULL
                            ELSE payload_json
                        END
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :batch_id
                      AND status = 'PROCESSING'
                    """
                ),
                {
                    "status": status,
                    "retry_count": next_retry,
                    "error_code": error_code,
                    "error_summary": error_summary,
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "batch_id": batch_id,
                },
            )
            if status == "DLQ_EXHAUSTED":
                await connection.execute(
                    text(
                        """
                        INSERT INTO public.alerts (
                            organization_id, id, alert_rule_id, device_id,
                            severity, status, message
                        ) VALUES (
                            :organization_id, :alert_id, NULL, :device_id,
                            'CRITICAL', 'OPEN',
                            'Metric batch exhausted all reprocessing attempts'
                        )
                        ON CONFLICT (organization_id, id) DO NOTHING
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "alert_id": uuid5(batch_id, "dlq-exhausted"),
                        "device_id": device_id,
                    },
                )
                await self._append_audit(
                    connection,
                    organization_id=organization_id,
                    actor_id=None,
                    actor_type="SYSTEM",
                    action="METRIC_BATCH.DLQ_EXHAUSTED",
                    batch_id=batch_id,
                    status="FAILURE",
                    details={"error_code": error_code},
                )
        return status

    async def list_active_organization_ids(self) -> tuple[UUID, ...]:
        async with self._engine.begin() as connection:
            if "sqlite" not in self._engine.dialect.name:
                await connection.execute(text("SET LOCAL ROLE nexus_app_user"))
                result = await connection.execute(
                    text("SELECT id FROM public.list_active_tenant_ids()")
                )
            else:
                result = await connection.execute(
                    text(
                        """
                        SELECT id
                        FROM public.organizations
                        WHERE is_active = true
                        ORDER BY created_at
                        """
                    )
                )
            return tuple(row["id"] for row in result.mappings().all())

    async def evaluate_alerts(
        self,
        *,
        organization_id: UUID,
        now: datetime | None = None,
    ) -> tuple[AlertSummary, ...]:
        current_time = datetime.now(UTC) if now is None else now
        results: list[AlertSummary] = []
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            rules_result = await connection.execute(
                text(
                    """
                    SELECT id, name, metric_name, operator, threshold_value,
                           duration_seconds, severity
                    FROM public.alert_rules
                    WHERE organization_id = :organization_id
                      AND is_enabled = true
                    """
                ),
                {"organization_id": organization_id},
            )
            rules = rules_result.mappings().all()
            for rule in rules:
                rule_obj = AlertRule(
                    id=rule["id"],
                    metric_name=rule["metric_name"],
                    operator=rule["operator"],
                    threshold_value=float(rule["threshold_value"]),
                    duration_seconds=rule["duration_seconds"],
                    severity=rule["severity"],
                )
                window_start = current_time - timedelta(
                    seconds=max(rule["duration_seconds"] * 2, 300)
                )
                devices_result = await connection.execute(
                    text(
                        """
                        SELECT DISTINCT device_id
                        FROM public.metric_samples
                        WHERE organization_id = :organization_id
                          AND metric_name = :metric_name
                          AND recorded_at >= :window_start
                          AND recorded_at <= :now
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "metric_name": rule["metric_name"],
                        "window_start": window_start,
                        "now": current_time,
                    },
                )
                device_ids = [
                    row["device_id"] for row in devices_result.mappings().all()
                ]
                for device_id in device_ids:
                    samples_result = await connection.execute(
                        text(
                            """
                            SELECT recorded_at, metric_value
                            FROM public.metric_samples
                            WHERE organization_id = :organization_id
                              AND device_id = :device_id
                              AND metric_name = :metric_name
                              AND recorded_at >= :window_start
                              AND recorded_at <= :now
                            ORDER BY recorded_at ASC
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "device_id": device_id,
                            "metric_name": rule["metric_name"],
                            "window_start": window_start,
                            "now": current_time,
                        },
                    )
                    samples = [
                        (row["recorded_at"], float(row["metric_value"]))
                        for row in samples_result.mappings().all()
                    ]
                    triggered = evaluate_rule(rule_obj, samples, now=current_time)

                    existing_result = await connection.execute(
                        text(
                            """
                            SELECT id, status, severity, message, triggered_at, resolved_at
                            FROM public.alerts
                            WHERE organization_id = :organization_id
                              AND alert_rule_id = :rule_id
                              AND device_id = :device_id
                              AND status IN ('OPEN', 'ACKNOWLEDGED', 'SUPPRESSED')
                            ORDER BY triggered_at DESC
                            LIMIT 1
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "rule_id": rule["id"],
                            "device_id": device_id,
                        },
                    )
                    existing = existing_result.mappings().first()

                    if triggered and existing is None:
                        alert_id = uuid4()
                        msg = (
                            f"Regla '{rule['name']}': {rule['metric_name']} "
                            f"{rule['operator']} {rule['threshold_value']}"
                        )
                        insert_res = await connection.execute(
                            text(
                                """
                                INSERT INTO public.alerts (
                                    organization_id, id, alert_rule_id, device_id,
                                    severity, status, message, triggered_at
                                ) VALUES (
                                    :organization_id, :alert_id, :rule_id, :device_id,
                                    :severity, 'OPEN', :message, :now
                                )
                                RETURNING id, device_id, alert_rule_id, severity, status, message, triggered_at, resolved_at
                                """
                            ),
                            {
                                "organization_id": organization_id,
                                "alert_id": alert_id,
                                "rule_id": rule["id"],
                                "device_id": device_id,
                                "severity": rule["severity"],
                                "message": msg,
                                "now": current_time,
                            },
                        )
                        row = insert_res.mappings().first()
                        if row:
                            results.append(
                                AlertSummary(
                                    id=row["id"],
                                    device_id=row["device_id"],
                                    alert_rule_id=row["alert_rule_id"],
                                    severity=row["severity"],
                                    status=row["status"],
                                    message=row["message"],
                                    triggered_at=row["triggered_at"],
                                    resolved_at=row["resolved_at"],
                                )
                            )
                    elif (
                        not triggered
                        and existing is not None
                        and existing["status"] in ("OPEN", "ACKNOWLEDGED")
                    ):
                        update_res = await connection.execute(
                            text(
                                """
                                UPDATE public.alerts
                                SET status = 'RESOLVED', resolved_at = :now
                                WHERE organization_id = :organization_id
                                  AND id = :alert_id
                                RETURNING id, device_id, alert_rule_id, severity, status, message, triggered_at, resolved_at
                                """
                            ),
                            {
                                "organization_id": organization_id,
                                "alert_id": existing["id"],
                                "now": current_time,
                            },
                        )
                        row = update_res.mappings().first()
                        if row:
                            results.append(
                                AlertSummary(
                                    id=row["id"],
                                    device_id=row["device_id"],
                                    alert_rule_id=row["alert_rule_id"],
                                    severity=row["severity"],
                                    status=row["status"],
                                    message=row["message"],
                                    triggered_at=row["triggered_at"],
                                    resolved_at=row["resolved_at"],
                                )
                            )
        return tuple(results)
