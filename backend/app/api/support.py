"""Versioned help desk and controlled remote action endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import hashlib
from typing import Annotated, cast
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_serializer

from backend.app.api.dependencies import require_csrf, require_permission
from backend.app.api.devices import require_agent
from backend.app.auth.session import (
    AuthorizationRejected,
    SessionIdentity,
    SessionUnavailable,
)
from backend.app.devices.service import AgentIdentity
from backend.app.support.schemas import (
    ActionRequest,
    ActionResultCreate,
    CommentCreate,
    TicketCreate,
    TicketTransition,
    MAX_ATTACHMENT_BYTES,
)
from backend.app.support.service import (
    ActionApproval,
    ActionAcknowledgement,
    ActionCommand,
    ActionResult,
    AttachmentRecord,
    CommentRecord,
    RequestTrace,
    SupportConflict,
    SupportInvalid,
    SupportNotFound,
    SupportService,
    SupportUnavailable,
    build_action_signing_payload,
    TicketRecord,
)


support_router = APIRouter(tags=["support"])


class TicketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    device_id: UUID | None
    alert_id: UUID | None
    created_by: UUID
    assigned_to: UUID | None
    ticket_number: str
    title: str
    description: str
    status: str
    priority: str
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TicketListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[TicketResponse, ...]
    next_cursor: UUID | None


class CommentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    ticket_id: UUID
    user_id: UUID
    is_internal: bool
    content: str
    created_at: datetime


class CommentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[CommentResponse, ...]
    next_cursor: UUID | None


class TicketStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str


class ActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    id: UUID
    device_id: UUID
    action_name: str
    nonce: UUID
    key_version: int | None
    issued_at: datetime
    expires_at: datetime
    signature: str | None
    parameters: dict[str, object]
    parameters_canonical: str
    action_version: int
    order_digest: str | None
    status: str

    @field_serializer("issued_at", "expires_at")
    def serialize_signed_time(self, value: datetime) -> str:
        # Match the canonical bytes signed by build_action_signing_payload.
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ActionApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str


class ActionResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    is_replay: bool


class ActionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[ActionResponse, ...]


class ActionAcknowledgementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    is_replay: bool


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    ticket_id: UUID
    original_name: str
    mime_type: str
    file_size: int
    uploaded_at: datetime


def get_support_application(request: Request) -> SupportService:
    application = getattr(request.app.state, "support_application", None)
    if application is None:
        raise SessionUnavailable
    return cast(SupportService, application)


def _csrf_permission(
    permission: str,
) -> Callable[..., Awaitable[SessionIdentity]]:
    async def dependency(
        identity: SessionIdentity = Depends(require_csrf),
    ) -> SessionIdentity:
        if permission not in identity.permissions:
            raise AuthorizationRejected
        return identity

    return dependency


def _trace(request: Request) -> RequestTrace:
    client = request.client.host if request.client is not None else None
    user_agent = request.headers.get("user-agent")
    if user_agent is not None:
        user_agent = user_agent[:255]
    return RequestTrace(ip_address=client, user_agent=user_agent)


def _tenant(identity: SessionIdentity) -> UUID:
    if identity.organization_id is None:
        raise SessionUnavailable
    return identity.organization_id


async def _read_attachment_body(request: Request) -> bytes:
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_ATTACHMENT_BYTES:
                raise SupportInvalid
        except ValueError:
            raise SupportInvalid from None
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise SupportInvalid
    if not content:
        raise SupportInvalid
    return bytes(content)


def _ticket_response(ticket: TicketRecord) -> TicketResponse:
    return TicketResponse(
        id=ticket.id,
        device_id=ticket.device_id,
        alert_id=ticket.alert_id,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        ticket_number=ticket.ticket_number,
        title=ticket.title,
        description=ticket.description,
        status=ticket.status,
        priority=ticket.priority,
        resolved_at=ticket.resolved_at,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _action_response(action: ActionCommand) -> ActionResponse:
    return ActionResponse(
        organization_id=action.organization_id,
        id=action.id,
        device_id=action.device_id,
        action_name=action.action_name,
        nonce=action.nonce,
        key_version=action.key_version,
        issued_at=action.issued_at,
        expires_at=action.expires_at,
        signature=action.signature,
        parameters=action.parameters,
        parameters_canonical=action.parameters_canonical,
        action_version=1,
        order_digest=(
            hashlib.sha256(build_action_signing_payload(action)).hexdigest()
            if action.key_version is not None else None
        ),
        status=action.status,
    )


@support_router.post("/tickets", response_model=TicketResponse, status_code=201)
async def create_ticket(
    payload: TicketCreate,
    request: Request,
    identity: SessionIdentity = Depends(_csrf_permission("tickets:create")),
    application: SupportService = Depends(get_support_application),
) -> TicketResponse:
    ticket = await application.create_ticket(
        organization_id=_tenant(identity),
        actor_id=identity.user_id,
        request=payload,
        trace=_trace(request),
    )
    return _ticket_response(ticket)


@support_router.get("/tickets", response_model=TicketListResponse)
async def list_tickets(
    identity: SessionIdentity = Depends(require_permission("tickets:read")),
    application: SupportService = Depends(get_support_application),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: UUID | None = None,
) -> TicketListResponse:
    items, next_cursor = await application.list_tickets(
        organization_id=_tenant(identity),
        actor_id=identity.user_id,
        can_read_all="tickets:internal_notes" in identity.permissions,
        limit=limit,
        after_id=after,
    )
    return TicketListResponse(
        items=tuple(_ticket_response(ticket) for ticket in items),
        next_cursor=next_cursor,
    )


@support_router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: UUID,
    identity: SessionIdentity = Depends(require_permission("tickets:read")),
    application: SupportService = Depends(get_support_application),
) -> TicketResponse:
    ticket = await application.get_ticket(
        organization_id=_tenant(identity),
        ticket_id=ticket_id,
        actor_id=identity.user_id,
        can_read_all="tickets:internal_notes" in identity.permissions,
    )
    return _ticket_response(ticket)


@support_router.delete("/tickets/{ticket_id}", status_code=204)
async def delete_ticket(
    ticket_id: UUID,
    request: Request,
    identity: SessionIdentity = Depends(_csrf_permission("tickets:create")),
    application: SupportService = Depends(get_support_application),
) -> None:
    await application.delete_ticket(
        organization_id=_tenant(identity),
        ticket_id=ticket_id,
        actor_id=identity.user_id,
        can_delete_any="tickets:internal_notes" in identity.permissions,
        trace=_trace(request),
    )


@support_router.post(
    "/tickets/{ticket_id}/comments",
    response_model=CommentResponse,
    status_code=201,
)
async def add_ticket_comment(
    ticket_id: UUID,
    payload: CommentCreate,
    request: Request,
    identity: SessionIdentity = Depends(_csrf_permission("tickets:create")),
    application: SupportService = Depends(get_support_application),
) -> CommentResponse:
    if payload.is_internal and "tickets:internal_notes" not in identity.permissions:
        raise AuthorizationRejected
    comment: CommentRecord = await application.add_comment(
        organization_id=_tenant(identity),
        ticket_id=ticket_id,
        actor_id=identity.user_id,
        request=payload,
        owner_only="tickets:internal_notes" not in identity.permissions,
        trace=_trace(request),
    )
    return CommentResponse(
        id=comment.id,
        ticket_id=comment.ticket_id,
        user_id=comment.user_id,
        is_internal=comment.is_internal,
        content=comment.content,
        created_at=comment.created_at,
    )


@support_router.get(
    "/tickets/{ticket_id}/comments", response_model=CommentListResponse
)
async def list_ticket_comments(
    ticket_id: UUID,
    identity: SessionIdentity = Depends(require_permission("tickets:read")),
    application: SupportService = Depends(get_support_application),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: UUID | None = None,
) -> CommentListResponse:
    can_read_all = "tickets:internal_notes" in identity.permissions
    comments, next_cursor = await application.list_comments(
        organization_id=_tenant(identity),
        ticket_id=ticket_id,
        actor_id=identity.user_id,
        include_internal=can_read_all,
        can_read_all=can_read_all,
        limit=limit,
        after_id=after,
    )
    return CommentListResponse(
        items=tuple(
            CommentResponse(
                id=comment.id,
                ticket_id=comment.ticket_id,
                user_id=comment.user_id,
                is_internal=comment.is_internal,
                content=comment.content,
                created_at=comment.created_at,
            )
            for comment in comments
        ),
        next_cursor=next_cursor,
    )


@support_router.post(
    "/tickets/{ticket_id}/attachments",
    response_model=AttachmentResponse,
    status_code=201,
)
async def upload_ticket_attachment(
    ticket_id: UUID,
    request: Request,
    original_name: Annotated[
        str, Header(alias="X-File-Name", min_length=1, max_length=255)
    ],
    identity: SessionIdentity = Depends(_csrf_permission("tickets:create")),
    application: SupportService = Depends(get_support_application),
) -> AttachmentResponse:
    attachment = await application.upload_attachment(
        organization_id=_tenant(identity),
        ticket_id=ticket_id,
        actor_id=identity.user_id,
        original_name=original_name,
        content=await _read_attachment_body(request),
        owner_only="tickets:internal_notes" not in identity.permissions,
        trace=_trace(request),
    )
    return AttachmentResponse(
        id=attachment.id,
        ticket_id=attachment.ticket_id,
        original_name=attachment.original_name,
        mime_type=attachment.mime_type,
        file_size=attachment.file_size,
        uploaded_at=attachment.uploaded_at,
    )


@support_router.get("/tickets/{ticket_id}/attachments/{attachment_id}")
async def download_ticket_attachment(
    ticket_id: UUID,
    attachment_id: UUID,
    identity: SessionIdentity = Depends(require_permission("tickets:read")),
    application: SupportService = Depends(get_support_application),
) -> Response:
    attachment = await application.download_attachment(
        organization_id=_tenant(identity),
        ticket_id=ticket_id,
        attachment_id=attachment_id,
        actor_id=identity.user_id,
        can_read_all="tickets:internal_notes" in identity.permissions,
    )
    encoded_name = quote(attachment.original_name, safe="")
    return Response(
        content=attachment.content,
        media_type=attachment.mime_type,
        headers={
            "Content-Disposition": (
                "attachment; filename=\"attachment\"; "
                f"filename*=UTF-8''{encoded_name}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@support_router.delete(
    "/tickets/{ticket_id}/attachments/{attachment_id}", status_code=204
)
async def delete_ticket_attachment(
    ticket_id: UUID,
    attachment_id: UUID,
    request: Request,
    identity: SessionIdentity = Depends(_csrf_permission("tickets:create")),
    application: SupportService = Depends(get_support_application),
) -> None:
    await application.delete_attachment(
        organization_id=_tenant(identity),
        ticket_id=ticket_id,
        attachment_id=attachment_id,
        actor_id=identity.user_id,
        owner_only="tickets:internal_notes" not in identity.permissions,
        trace=_trace(request),
    )


@support_router.patch(
    "/tickets/{ticket_id}/status", response_model=TicketStatusResponse
)
async def transition_ticket(
    ticket_id: UUID,
    payload: TicketTransition,
    request: Request,
    identity: SessionIdentity = Depends(
        _csrf_permission("tickets:update_status")
    ),
    application: SupportService = Depends(get_support_application),
) -> TicketStatusResponse:
    if "tickets:internal_notes" not in identity.permissions:
        raise AuthorizationRejected
    changed = await application.transition_ticket(
        organization_id=_tenant(identity),
        ticket_id=ticket_id,
        actor_id=identity.user_id,
        expected_status=payload.expected_status,
        target_status=payload.status,
        assigned_to=payload.assigned_to,
        trace=_trace(request),
    )
    return TicketStatusResponse(id=changed.ticket_id, status=changed.target_status)


@support_router.post(
    "/devices/{device_id}/actions", response_model=ActionResponse, status_code=201
)
async def request_remote_action(
    device_id: UUID,
    payload: ActionRequest,
    request: Request,
    identity: SessionIdentity = Depends(
        _csrf_permission("actions:request_exec")
    ),
    application: SupportService = Depends(get_support_application),
) -> ActionResponse:
    action = await application.request_action(
        organization_id=_tenant(identity),
        device_id=device_id,
        actor_id=identity.user_id,
        request=payload,
        trace=_trace(request),
    )
    return _action_response(action)


async def require_action_viewer(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> tuple[UUID, UUID | None]:
    if authorization is not None:
        agent_app = getattr(request.app.state, "agent_token_application", None)
        limiter = getattr(request.app.state, "agent_request_rate_limiter", None)
        if agent_app is None or limiter is None:
            raise HTTPException(status_code=503, detail="Servicio temporalmente no disponible")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token or token.strip() != token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Autenticación de agente requerida",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            await limiter.preflight(token, request.client.host if request.client else "invalid")
            identity = await agent_app.authenticate(token)
            return identity.organization_id, identity.device_id
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Autenticación de agente requerida",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None

    session_app = getattr(request.app.state, "session_application", None)
    if session_app is None:
        raise SessionUnavailable
    session_cookie = request.cookies.get("__Host-nexus_session")
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
        )
    session_identity = await session_app.authenticate(
        session_cookie, require_organization=True
    )
    if session_identity.organization_id is None:
        raise SessionUnavailable
    if not ({"actions:request_exec", "actions:approve_admin", "devices:read"} & set(session_identity.permissions)):
        raise AuthorizationRejected
    return session_identity.organization_id, None


@support_router.get(
    "/devices/{device_id}/actions", response_model=ActionListResponse
)
async def poll_remote_actions(
    device_id: UUID,
    auth_ctx: tuple[UUID, UUID | None] = Depends(require_action_viewer),
    application: SupportService = Depends(get_support_application),
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> ActionListResponse:
    organization_id, agent_device_id = auth_ctx
    if agent_device_id is not None and agent_device_id != device_id:
        raise SupportNotFound
    actions = await application.poll_actions(
        organization_id=organization_id,
        device_id=device_id,
        limit=limit,
    )
    return ActionListResponse(
        items=tuple(_action_response(action) for action in actions)
    )


@support_router.post(
    "/devices/{device_id}/actions/{action_id}/ack",
    response_model=ActionAcknowledgementResponse,
)
async def acknowledge_remote_action(
    device_id: UUID,
    action_id: UUID,
    request: Request,
    identity: AgentIdentity = Depends(require_agent),
    application: SupportService = Depends(get_support_application),
) -> ActionAcknowledgementResponse:
    if identity.device_id != device_id:
        raise SupportNotFound
    acknowledgement: ActionAcknowledgement = await application.acknowledge_action(
        organization_id=identity.organization_id,
        device_id=device_id,
        action_id=action_id,
        token_id=identity.token_id,
        trace=_trace(request),
    )
    return ActionAcknowledgementResponse(
        status=acknowledgement.status,
        is_replay=acknowledgement.is_replay,
    )


@support_router.post(
    "/actions/{action_id}/approval", response_model=ActionApprovalResponse
)
async def approve_remote_action(
    action_id: UUID,
    request: Request,
    identity: SessionIdentity = Depends(
        _csrf_permission("actions:approve_admin")
    ),
    application: SupportService = Depends(get_support_application),
) -> ActionApprovalResponse:
    approval: ActionApproval = await application.approve_action(
        organization_id=_tenant(identity),
        action_id=action_id,
        approver_id=identity.user_id,
        trace=_trace(request),
    )
    return ActionApprovalResponse(id=approval.action_id, status=approval.status)


@support_router.post(
    "/devices/{device_id}/actions/{action_id}/result",
    response_model=ActionResultResponse,
)
async def report_remote_action_result(
    device_id: UUID,
    action_id: UUID,
    payload: ActionResultCreate,
    request: Request,
    identity: AgentIdentity = Depends(require_agent),
    application: SupportService = Depends(get_support_application),
) -> ActionResultResponse:
    if identity.device_id != device_id:
        raise SupportNotFound
    result: ActionResult = await application.record_action_result(
        organization_id=identity.organization_id,
        device_id=device_id,
        action_id=action_id,
        token_id=identity.token_id,
        result=payload,
        trace=_trace(request),
    )
    return ActionResultResponse(status=result.status, is_replay=result.is_replay)


def install_support_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        SupportInvalid,
        lambda _request, _error: JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Solicitud inválida",
                }
            },
        ),
    )
    app.add_exception_handler(
        SupportNotFound,
        lambda _request, _error: JSONResponse(
            status_code=404,
            content={
                "error": {"code": "NOT_FOUND", "message": "Recurso no encontrado"}
            },
        ),
    )
    app.add_exception_handler(
        SupportConflict,
        lambda _request, _error: JSONResponse(
            status_code=409,
            content={
                "error": {"code": "CONFLICT", "message": "Conflicto de estado"}
            },
        ),
    )
    app.add_exception_handler(
        SupportUnavailable,
        lambda _request, _error: JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": "Servicio temporalmente no disponible",
                }
            },
        ),
    )
