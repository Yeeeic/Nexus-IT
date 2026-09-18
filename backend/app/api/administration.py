"""Versioned tenant RBAC and audit endpoints."""

from datetime import datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.administration.service import Administration, AdministrationRejected
from backend.app.api.dependencies import require_permission
from backend.app.auth.session import SessionIdentity, SessionUnavailable


administration_router = APIRouter(tags=["administration"])
PermissionName = Annotated[
    str,
    Field(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$",
    ),
]


class PermissionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    description: str


class PermissionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[PermissionItem, ...]


class RoleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str
    is_system: bool
    permissions: tuple[str, ...]


class RoleListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[RoleResponse, ...]


class RoleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    description: str = Field(min_length=1, max_length=255)
    permissions: list[PermissionName] = Field(min_length=1, max_length=50)

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("permissions must be unique")
        return value


class RoleAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    user_id: UUID

    @field_validator("user_id", mode="before")
    @classmethod
    def parse_user_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            return UUID(value)
        return value


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    actor_id: UUID | None
    actor_type: str
    action: str
    resource_type: str
    resource_id: UUID | None
    status: str
    details: dict[str, str]
    created_at: datetime


class AuditLogListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[AuditLogResponse, ...]


def get_administration(request: Request) -> Administration:
    administration = getattr(request.app.state, "administration", None)
    if administration is None:
        raise SessionUnavailable
    return cast(Administration, administration)


def _organization(identity: SessionIdentity) -> UUID:
    if identity.organization_id is None:
        raise SessionUnavailable
    return identity.organization_id


def _role_response(role: Any) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=role.permissions,
    )


def _audit_response(entry: Any) -> AuditLogResponse:
    return AuditLogResponse(
        id=entry.id,
        actor_id=entry.actor_id,
        actor_type=entry.actor_type,
        action=entry.action,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        status=entry.status,
        details=entry.details,
        created_at=entry.created_at,
    )


CANONICAL_PERMISSIONS: tuple[PermissionItem, ...] = (
    PermissionItem(code="org:read_settings", name="Lectura de Configuración", description="Consultar parámetros de la organización"),
    PermissionItem(code="org:update_settings", name="Actualizar Configuración", description="Modificar parámetros de la organización"),
    PermissionItem(code="users:manage", name="Gestión de Usuarios", description="Administrar usuarios y accesos de la organización"),
    PermissionItem(code="roles:manage_custom", name="Gestión de Roles", description="Crear y asignar roles personalizados"),
    PermissionItem(code="devices:read", name="Lectura de Dispositivos", description="Consultar inventario y estado de la flota"),
    PermissionItem(code="devices:enroll", name="Enrolamiento de Equipos", description="Registrar nuevos dispositivos y tokens de agente"),
    PermissionItem(code="devices:delete", name="Eliminación de Equipos", description="Dar de baja dispositivos del parque"),
    PermissionItem(code="metrics:read_telemetry", name="Lectura de Telemetría", description="Visualizar métricas en tiempo real e históricas"),
    PermissionItem(code="metrics:retry_dlq", name="Reintentar Lotes DLQ", description="Reprocesar lotes fallidos en cola dead-letter"),
    PermissionItem(code="metrics:export_dlq_diagnostics", name="Diagnóstico de DLQ", description="Consultar resúmenes sanitizados de fallos"),
    PermissionItem(code="metrics:decide_dlq", name="Decisión de Lotes DLQ", description="Resolver y purgar lotes exhaustos"),
    PermissionItem(code="inventory:read", name="Lectura de Inventario", description="Consultar hardware, software y servicios"),
    PermissionItem(code="alerts:read", name="Lectura de Alertas", description="Consultar incidentes y alertas activas"),
    PermissionItem(code="alerts:manage_rules", name="Gestión de Reglas de Alerta", description="Configurar umbrales de monitoreo"),
    PermissionItem(code="tickets:read", name="Lectura de Tickets", description="Consultar requerimientos de soporte"),
    PermissionItem(code="tickets:create", name="Creación de Tickets", description="Crear requerimientos y adjuntar archivos"),
    PermissionItem(code="tickets:update_status", name="Actualizar Estado de Tickets", description="Transicionar estados en mesa de ayuda"),
    PermissionItem(code="tickets:internal_notes", name="Notas Internas de Soporte", description="Gestionar comentarios privados del equipo técnico"),
    PermissionItem(code="actions:request_exec", name="Solicitar Acciones Remotas", description="Despachar comandos del catálogo cerrado"),
    PermissionItem(code="actions:approve_admin", name="Aprobar Acciones Remotas", description="Autorización administrativa y firma Ed25519"),
    PermissionItem(code="audit:read_logs", name="Lectura de Auditoría", description="Consultar registros append-only de auditoría"),
)


@administration_router.get("/permissions", response_model=PermissionListResponse)
async def list_permissions(
    identity: SessionIdentity = Depends(
        require_permission("roles:manage_custom")
    ),
) -> PermissionListResponse:
    return PermissionListResponse(items=CANONICAL_PERMISSIONS)


@administration_router.get("/roles", response_model=RoleListResponse)
async def list_roles(
    identity: SessionIdentity = Depends(
        require_permission("roles:manage_custom")
    ),
    administration: Administration = Depends(get_administration),
) -> RoleListResponse:
    roles = await administration.list_roles(_organization(identity))
    return RoleListResponse(
        items=tuple(_role_response(role) for role in roles)
    )


@administration_router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_role(
    payload: RoleCreateRequest,
    identity: SessionIdentity = Depends(
        require_permission("roles:manage_custom", csrf=True)
    ),
    administration: Administration = Depends(get_administration),
) -> RoleResponse | JSONResponse:
    try:
        role = await administration.create_role(
            organization_id=_organization(identity),
            actor_id=identity.user_id,
            name=payload.name,
            description=payload.description,
            permissions=tuple(payload.permissions),
        )
    except AdministrationRejected:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_ROLE", "message": "Rol o permisos invÃ¡lidos"}},
        )
    return _role_response(role)


@administration_router.post(
    "/roles/{role_id}/assignments",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def assign_role(
    role_id: UUID,
    payload: RoleAssignmentRequest,
    identity: SessionIdentity = Depends(
        require_permission("roles:manage_custom", csrf=True)
    ),
    administration: Administration = Depends(get_administration),
) -> Response | JSONResponse:
    try:
        await administration.assign_role(
            organization_id=_organization(identity),
            actor_id=identity.user_id,
            role_id=role_id,
            user_id=payload.user_id,
        )
    except AdministrationRejected:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "RESOURCE_NOT_FOUND", "message": "Recurso no encontrado"}},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@administration_router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
)
async def list_audit_logs(
    identity: SessionIdentity = Depends(require_permission("audit:read_logs")),
    administration: Administration = Depends(get_administration),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: datetime | None = None,
    action: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> AuditLogListResponse:
    entries = await administration.list_audit_logs(
        organization_id=_organization(identity),
        limit=limit,
        before=before,
        action=action,
    )
    return AuditLogListResponse(
        items=tuple(_audit_response(entry) for entry in entries)
    )
