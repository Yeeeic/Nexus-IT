"""Versioned APIs for agent metric ingestion and tenant telemetry."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.dependencies import (
    require_csrf,
    require_permission,
)
from backend.app.auth.session import (
    AuthorizationRejected,
    SessionIdentity,
    SessionUnavailable,
)
from backend.app.devices.service import AgentTokenRejected, AgentTokenUnavailable
from backend.app.metrics.rate_limit import (
    MetricIngestRateLimiter,
    MetricRateLimited,
    MetricRateLimitUnavailable,
)
from backend.app.metrics.schemas import (
    AlertRuleInput,
    BatchDecisionInput,
    BatchRetryInput,
    BatchStatusQueryInput,
    MetricBatchInput,
    MetricReuploadInput,
)
from backend.app.metrics.service import (
    AgentMetricAuthenticator,
    AgentMetricIdentity,
    BatchDecisionConflict,
    BatchDigestMismatch,
    BatchIdentityCollision,
    BatchNotFound,
    BatchStateRejected,
    BatchStatusRecord,
    MetricAccessRejected,
    MetricAuditContext,
    MetricsApplication,
    MetricsUnavailable,
)


MAX_METRIC_BATCH_BYTES = 512 * 1024
metrics_router = APIRouter(tags=["metrics"])


class MetricsApplicationContract(Protocol):
    async def ingest_batch(
        self,
        identity: AgentMetricIdentity,
        device_id: UUID,
        batch: MetricBatchInput,
    ): ...

    async def list_telemetry(
        self,
        organization_id: UUID,
        device_id: UUID,
        *,
        actor_id: UUID,
        assigned_only: bool,
        metric_name: str | None,
        limit: int,
    ): ...

    async def create_alert_rule(
        self,
        organization_id: UUID,
        actor_id: UUID,
        rule: AlertRuleInput,
    ): ...

    async def list_alert_rules(
        self,
        organization_id: UUID,
    ): ...

    async def list_alerts(
        self,
        organization_id: UUID,
        *,
        limit: int,
    ): ...

    async def get_agent_batch_status(
        self,
        identity: AgentMetricIdentity,
        device_id: UUID,
        batch_id: UUID,
    ): ...

    async def get_agent_batch_statuses(
        self,
        identity: AgentMetricIdentity,
        device_id: UUID,
        batch_ids: tuple[UUID, ...],
    ): ...

    async def authorize_retry(
        self,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        actor_id: UUID,
        retry: BatchRetryInput,
        audit: MetricAuditContext,
    ): ...

    async def reupload_batch(
        self,
        identity: AgentMetricIdentity,
        device_id: UUID,
        batch_id: UUID,
        payload: MetricReuploadInput,
    ): ...

    async def export_diagnostics(
        self,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
    ): ...

    async def decide_exhausted_batch(
        self,
        organization_id: UUID,
        device_id: UUID,
        batch_id: UUID,
        actor_id: UUID,
        decision: BatchDecisionInput,
        audit: MetricAuditContext,
    ): ...


class BatchReceiptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    status: Literal[
        "RECEIVED",
        "PROCESSING",
        "PROCESSED",
        "DLQ",
        "AWAITING_REUPLOAD",
        "DLQ_EXHAUSTED",
    ]
    duplicate: bool


class BatchStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    status: Literal[
        "RECEIVED",
        "PROCESSING",
        "PROCESSED",
        "DLQ",
        "AWAITING_REUPLOAD",
        "DLQ_EXHAUSTED",
    ]
    retry_count: Annotated[int, Field(ge=0, le=3)]
    reprocess_count: Annotated[int, Field(ge=0, le=3)]
    error_code: str | None
    decision: Literal["PURGE_LOCAL", "RETAIN"] | None


class BatchStatusQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statuses: dict[UUID, BatchStatusResponse]


class BatchDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    status: Literal[
        "RECEIVED",
        "PROCESSING",
        "PROCESSED",
        "DLQ",
        "AWAITING_REUPLOAD",
        "DLQ_EXHAUSTED",
    ]
    retry_count: Annotated[int, Field(ge=0, le=3)]
    reprocess_count: Annotated[int, Field(ge=0, le=3)]
    payload_digest: str
    error_code: str | None
    error_summary: str | None
    received_at: datetime
    processed_at: datetime | None


class TelemetrySampleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    device_id: UUID
    metric_name: str
    metric_value: float
    recorded_at: datetime
    labels: dict[str, str]


class TelemetryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[TelemetrySampleResponse, ...]


class AlertRuleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    metric_name: str
    operator: Literal["GT", "GTE", "LT", "LTE", "EQ"]
    threshold_value: Decimal
    duration_seconds: int
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    is_enabled: bool
    created_at: datetime


class AlertRuleListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[AlertRuleResponse, ...]


class AlertResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    device_id: UUID
    alert_rule_id: UUID | None
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    status: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"]
    message: str
    triggered_at: datetime
    resolved_at: datetime | None


class AlertListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[AlertResponse, ...]


def get_metrics_application(request: Request) -> MetricsApplicationContract:
    application = getattr(request.app.state, "metrics_application", None)
    if application is None:
        raise SessionUnavailable
    return cast(MetricsApplication, application)


def get_agent_authenticator(request: Request) -> AgentMetricAuthenticator:
    authenticator = getattr(
        request.app.state,
        "metric_agent_authenticator",
        None,
    )
    if authenticator is None:
        authenticator = getattr(
            request.app.state,
            "agent_token_application",
            None,
        )
    if authenticator is None:
        raise SessionUnavailable
    return cast(AgentMetricAuthenticator, authenticator)


def get_metric_rate_limiter(request: Request) -> MetricIngestRateLimiter:
    limiter = getattr(request.app.state, "metric_ingest_rate_limiter", None)
    if limiter is None:
        raise SessionUnavailable
    return cast(MetricIngestRateLimiter, limiter)


def _batch_status_response(record: BatchStatusRecord) -> BatchStatusResponse:
    return BatchStatusResponse.model_validate(record, from_attributes=True)


def _audit_context(request: Request) -> MetricAuditContext:
    return MetricAuditContext(
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    )


def _raise_batch_error(error: Exception) -> None:
    if isinstance(error, BatchNotFound):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lote no encontrado",
        ) from None
    if isinstance(
        error,
        (BatchStateRejected, BatchDecisionConflict, BatchDigestMismatch, BatchIdentityCollision),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operación incompatible con el estado del lote",
        ) from None
    if isinstance(error, MetricAccessRejected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Servicio temporalmente no disponible",
    ) from None


async def require_retry_manager(
    identity: SessionIdentity = Depends(require_csrf),
) -> SessionIdentity:
    if "metrics:retry_dlq" not in identity.permissions:
        raise AuthorizationRejected
    return identity


async def require_diagnostics_reader(
    identity: SessionIdentity = Depends(
        require_permission("metrics:export_dlq_diagnostics")
    ),
) -> SessionIdentity:
    return identity


async def require_decision_manager(
    identity: SessionIdentity = Depends(require_csrf),
) -> SessionIdentity:
    if "metrics:decide_dlq" not in identity.permissions:
        raise AuthorizationRejected
    return identity


async def require_metric_agent(
    authorization: Annotated[str | None, Header()] = None,
    authenticator: AgentMetricAuthenticator = Depends(get_agent_authenticator),
    limiter: MetricIngestRateLimiter = Depends(get_metric_rate_limiter),
) -> AgentMetricIdentity:
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
        )
    scheme, separator, token = authorization.partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not token
        or token.strip() != token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
        )
    if not 1 <= len(token) <= 512:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
        )
    try:
        identity = await authenticator.authenticate(token)
    except AgentTokenRejected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
        ) from None
    except AgentTokenUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        ) from None
    try:
        await limiter.allow(identity.organization_id, identity.token_id)
    except MetricRateLimited as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from None
    except MetricRateLimitUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        ) from None
    return identity


async def enforce_metric_batch_size(
    request: Request,
    content_length: Annotated[str | None, Header()] = None,
) -> None:
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = MAX_METRIC_BATCH_BYTES + 1
        if declared_size < 0 or declared_size > MAX_METRIC_BATCH_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Lote demasiado grande",
            )
    body = await request.body()
    if len(body) > MAX_METRIC_BATCH_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Lote demasiado grande",
        )


@metrics_router.post(
    "/devices/{device_id}/metrics/batches",
    response_model=BatchReceiptResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_metric_batch_size)],
)
async def ingest_metric_batch(
    device_id: UUID,
    batch: MetricBatchInput,
    identity: AgentMetricIdentity = Depends(require_metric_agent),
    application: MetricsApplicationContract = Depends(get_metrics_application),
) -> BatchReceiptResponse:
    try:
        receipt = await application.ingest_batch(identity, device_id, batch)
    except MetricAccessRejected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado",
        ) from None
    except (BatchDigestMismatch, BatchIdentityCollision):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El identificador del lote no coincide con su contenido",
        ) from None
    except MetricsUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        ) from None
    return BatchReceiptResponse(
        batch_id=receipt.batch_id,
        status=receipt.status,
        duplicate=receipt.duplicate,
    )


@metrics_router.get(
    "/devices/{device_id}/metrics/batches/{batch_id}",
    response_model=BatchStatusResponse,
)
async def get_metric_batch_status(
    device_id: UUID,
    batch_id: UUID,
    identity: AgentMetricIdentity = Depends(require_metric_agent),
    application: MetricsApplicationContract = Depends(get_metrics_application),
) -> BatchStatusResponse:
    try:
        record = await application.get_agent_batch_status(
            identity, device_id, batch_id
        )
    except (
        BatchNotFound,
        MetricAccessRejected,
        MetricsUnavailable,
    ) as error:
        _raise_batch_error(error)
    return _batch_status_response(record)


@metrics_router.post(
    "/devices/{device_id}/metrics/batches/status-query",
    response_model=BatchStatusQueryResponse,
)
async def query_metric_batch_statuses(
    device_id: UUID,
    query: BatchStatusQueryInput,
    identity: AgentMetricIdentity = Depends(require_metric_agent),
    application: MetricsApplicationContract = Depends(get_metrics_application),
) -> BatchStatusQueryResponse:
    try:
        records = await application.get_agent_batch_statuses(
            identity, device_id, query.batch_ids
        )
    except (MetricAccessRejected, MetricsUnavailable) as error:
        _raise_batch_error(error)
    return BatchStatusQueryResponse(
        statuses={record.batch_id: _batch_status_response(record) for record in records}
    )


@metrics_router.post(
    "/devices/{device_id}/metrics/batches/{batch_id}/retry",
    response_model=BatchStatusResponse,
)
async def retry_metric_batch(
    device_id: UUID,
    batch_id: UUID,
    retry: BatchRetryInput,
    request: Request,
    identity: SessionIdentity = Depends(require_retry_manager),
    application: MetricsApplicationContract = Depends(get_metrics_application),
) -> BatchStatusResponse:
    if identity.organization_id is None:
        raise SessionUnavailable
    try:
        record = await application.authorize_retry(
            identity.organization_id,
            device_id,
            batch_id,
            identity.user_id,
            retry,
            _audit_context(request),
        )
    except (BatchNotFound, BatchStateRejected, MetricsUnavailable) as error:
        _raise_batch_error(error)
    return _batch_status_response(record)


@metrics_router.post(
    "/devices/{device_id}/metrics/batches/{batch_id}/reupload",
    response_model=BatchReceiptResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_metric_batch_size)],
)
async def reupload_metric_batch(
    device_id: UUID,
    batch_id: UUID,
    payload: MetricReuploadInput,
    identity: AgentMetricIdentity = Depends(require_metric_agent),
    application: MetricsApplicationContract = Depends(get_metrics_application),
) -> BatchReceiptResponse:
    try:
        receipt = await application.reupload_batch(
            identity, device_id, batch_id, payload
        )
    except (
        BatchDigestMismatch,
        BatchIdentityCollision,
        BatchNotFound,
        BatchStateRejected,
        MetricAccessRejected,
        MetricsUnavailable,
    ) as error:
        _raise_batch_error(error)
    return BatchReceiptResponse(
        batch_id=receipt.batch_id,
        status=receipt.status,
        duplicate=receipt.duplicate,
    )


@metrics_router.get(
    "/devices/{device_id}/metrics/batches/{batch_id}/export-diagnostics",
    response_model=BatchDiagnosticsResponse,
)
async def export_metric_batch_diagnostics(
    device_id: UUID,
    batch_id: UUID,
    identity: SessionIdentity = Depends(require_diagnostics_reader),
    application: MetricsApplicationContract = Depends(get_metrics_application),
) -> BatchDiagnosticsResponse:
    if identity.organization_id is None:
        raise SessionUnavailable
    try:
        diagnostics = await application.export_diagnostics(
            identity.organization_id, device_id, batch_id
        )
    except (BatchNotFound, MetricsUnavailable) as error:
        _raise_batch_error(error)
    return BatchDiagnosticsResponse.model_validate(
        diagnostics,
        from_attributes=True,
    )


@metrics_router.post(
    "/devices/{device_id}/metrics/batches/{batch_id}/decision",
    response_model=BatchStatusResponse,
)
async def decide_metric_batch(
    device_id: UUID,
    batch_id: UUID,
    decision: BatchDecisionInput,
    request: Request,
    identity: SessionIdentity = Depends(require_decision_manager),
    application: MetricsApplicationContract = Depends(get_metrics_application),
) -> BatchStatusResponse:
    if identity.organization_id is None:
        raise SessionUnavailable
    try:
        record = await application.decide_exhausted_batch(
            identity.organization_id,
            device_id,
            batch_id,
            identity.user_id,
            decision,
            _audit_context(request),
        )
    except (
        BatchDecisionConflict,
        BatchNotFound,
        BatchStateRejected,
        MetricsUnavailable,
    ) as error:
        _raise_batch_error(error)
    return _batch_status_response(record)


@metrics_router.get(
    "/devices/{device_id}/metrics/telemetry",
    response_model=TelemetryResponse,
)
async def read_telemetry(
    device_id: UUID,
    identity: SessionIdentity = Depends(
        require_permission("metrics:read_telemetry")
    ),
    application: MetricsApplicationContract = Depends(get_metrics_application),
    metric_name: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            pattern=r"^[a-z][a-z0-9_.-]{0,99}$",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> TelemetryResponse:
    if identity.organization_id is None:
        raise SessionUnavailable
    try:
        samples = await application.list_telemetry(
            identity.organization_id,
            device_id,
            actor_id=identity.user_id,
            assigned_only="metrics:read_all" not in identity.permissions,
            metric_name=metric_name,
            limit=limit,
        )
    except MetricsUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        ) from None
    return TelemetryResponse(
        items=tuple(
            TelemetrySampleResponse(
                id=sample.id,
                device_id=sample.device_id,
                metric_name=sample.metric_name,
                metric_value=sample.metric_value,
                recorded_at=sample.recorded_at,
                labels=sample.labels,
            )
            for sample in samples
        )
    )


async def require_alert_rule_manager(
    identity: SessionIdentity = Depends(require_csrf),
) -> SessionIdentity:
    if "alerts:manage_rules" not in identity.permissions:
        raise AuthorizationRejected
    return identity


@metrics_router.get("/alert-rules", response_model=AlertRuleListResponse)
async def list_alert_rules(
    identity: SessionIdentity = Depends(require_permission("alerts:read")),
    application: MetricsApplicationContract = Depends(get_metrics_application),
) -> AlertRuleListResponse:
    if identity.organization_id is None:
        raise SessionUnavailable
    try:
        rules = await application.list_alert_rules(identity.organization_id)
    except MetricsUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        ) from None
    return AlertRuleListResponse(
        items=tuple(
            AlertRuleResponse.model_validate(r, from_attributes=True)
            for r in rules
        )
    )


@metrics_router.post(
    "/alert-rules",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert_rule(
    rule: AlertRuleInput,
    identity: SessionIdentity = Depends(require_alert_rule_manager),
    application: MetricsApplicationContract = Depends(get_metrics_application),
) -> AlertRuleResponse:
    if identity.organization_id is None:
        raise SessionUnavailable
    try:
        created = await application.create_alert_rule(
            identity.organization_id,
            identity.user_id,
            rule,
        )
    except MetricsUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        ) from None
    return AlertRuleResponse.model_validate(created, from_attributes=True)


@metrics_router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    identity: SessionIdentity = Depends(require_permission("alerts:read")),
    application: MetricsApplicationContract = Depends(get_metrics_application),
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> AlertListResponse:
    if identity.organization_id is None:
        raise SessionUnavailable
    try:
        alerts = await application.list_alerts(
            identity.organization_id,
            limit=limit,
        )
    except MetricsUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        ) from None
    return AlertListResponse(
        items=tuple(
            AlertResponse.model_validate(alert, from_attributes=True)
            for alert in alerts
        )
    )
