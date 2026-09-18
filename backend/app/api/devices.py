"""Versioned device enrollment, inventory, and agent endpoints."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.api.dependencies import require_csrf, require_permission
from backend.app.auth.session import AuthorizationRejected, SessionIdentity, SessionUnavailable
from backend.app.devices.service import (
    AgentIdentity,
    AgentTokenApplication,
    AgentTokenRejected,
    AgentTokenUnavailable,
    AuditContext,
    DeviceConflict,
    DeviceEnrollment,
    DeviceEnrollmentResult,
    DeviceNotFound,
    DeviceRecord,
    DeviceService,
    DeviceTokenResult,
    DeviceUpdate,
    InventorySnapshot,
    InventorySnapshotWrite,
)
from backend.app.devices.rate_limit import (
    AgentRequestLimited,
    AgentRequestLimitUnavailable,
    AgentRequestRateLimiter,
)


devices_router = APIRouter(prefix="/devices", tags=["devices"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DeviceEnrollmentRequest(StrictModel):
    hostname: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    token_expires_at: datetime | None = None

    @field_validator("hostname", "display_name", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("token_expires_at", mode="before")
    @classmethod
    def parse_token_expiry(cls, value: object) -> object:
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    @field_validator("token_expires_at")
    @classmethod
    def require_aware_token_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("token expiry must include timezone")
        return value


class DeviceUpdateRequest(StrictModel):
    display_name: str | None = Field(min_length=1, max_length=150)

    @field_validator("display_name", mode="before")
    @classmethod
    def strip_display_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class TokenRotationRequest(StrictModel):
    expires_at: datetime | None = None

    @field_validator("expires_at", mode="before")
    @classmethod
    def parse_expiry(cls, value: object) -> object:
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    @field_validator("expires_at")
    @classmethod
    def require_aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("token expiry must include timezone")
        return value


class DeviceAssignmentRequest(StrictModel):
    user_id: UUID

    @field_validator("user_id", mode="before")
    @classmethod
    def parse_user_id(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value


class DeviceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    hostname: str
    display_name: str | None
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeviceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[DeviceResponse, ...]
    next_cursor: UUID | None


class DeviceEnrollmentResponse(DeviceResponse):
    token_id: UUID
    token: str
    token_expires_at: datetime | None


class DeviceTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_id: UUID
    token: str
    expires_at: datetime | None


class HardwareInventory(StrictModel):
    cpu_model: str | None = Field(default=None, max_length=200)
    physical_cores: int | None = Field(default=None, ge=1, le=1024)
    logical_processors: int | None = Field(default=None, ge=1, le=4096)
    memory_bytes: int = Field(ge=0, le=2**63 - 1)


class SoftwarePackage(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=100)
    publisher: str | None = Field(default=None, max_length=255)
    architecture: Literal["X86", "X64", "ARM", "ARM64", "OTHER"] = "OTHER"


class PatchInventory(StrictModel):
    identifier: str = Field(min_length=1, max_length=100)
    status: Literal["INSTALLED", "PENDING_REBOOT", "FAILED"]


class ServiceInventory(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    status: Literal["RUNNING", "STOPPED", "UNKNOWN"]
    start_type: Literal["AUTO", "MANUAL", "DISABLED", "UNKNOWN"]


class InventoryWriteRequest(StrictModel):
    hardware: HardwareInventory
    software_packages: list[SoftwarePackage] = Field(default_factory=list, max_length=2000)
    patches: list[PatchInventory] = Field(default_factory=list, max_length=2000)
    services: list[ServiceInventory] = Field(default_factory=list, max_length=1000)
    collected_at: datetime

    @field_validator("collected_at", mode="before")
    @classmethod
    def parse_collected_at(cls, value: object) -> object:
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    @field_validator("collected_at")
    @classmethod
    def require_aware_collected_at(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("collection time must include timezone")
        return value


class InventoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: UUID
    hardware: dict[str, object]
    software_packages: tuple[dict[str, object], ...]
    patches: tuple[dict[str, object], ...]
    services: tuple[dict[str, object], ...]
    collected_at: datetime
    updated_at: datetime


def get_device_service(request: Request) -> DeviceService:
    service = getattr(request.app.state, "device_service", None)
    if service is None:
        raise SessionUnavailable
    return cast(DeviceService, service)


def get_agent_token_application(request: Request) -> AgentTokenApplication:
    application = getattr(request.app.state, "agent_token_application", None)
    if application is None:
        raise HTTPException(status_code=503, detail="Servicio temporalmente no disponible")
    return cast(AgentTokenApplication, application)


def get_agent_request_rate_limiter(request: Request) -> AgentRequestRateLimiter:
    limiter = getattr(request.app.state, "agent_request_rate_limiter", None)
    if limiter is None:
        raise HTTPException(status_code=503, detail="Servicio temporalmente no disponible")
    return cast(AgentRequestRateLimiter, limiter)


async def require_agent(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    application: AgentTokenApplication = Depends(get_agent_token_application),
    limiter: AgentRequestRateLimiter = Depends(get_agent_request_rate_limiter),
) -> AgentIdentity:
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación de agente requerida",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token or token.strip() != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación de agente requerida",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        await limiter.preflight(
            token,
            request.client.host if request.client else "invalid",
        )
    except AgentRequestLimited as error:
        raise HTTPException(
            status_code=429,
            detail="Demasiadas solicitudes",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from None
    except AgentRequestLimitUnavailable:
        raise HTTPException(status_code=503, detail="Servicio temporalmente no disponible") from None
    try:
        identity = await application.authenticate(token)
    except AgentTokenRejected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación de agente requerida",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except AgentTokenUnavailable:
        raise HTTPException(status_code=503, detail="Servicio temporalmente no disponible") from None
    request.state.agent_identity = identity
    return identity


def require_mutation_permission(
    permission: str,
) -> Callable[..., Awaitable[SessionIdentity]]:
    async def dependency(
        identity: SessionIdentity = Depends(require_csrf),
    ) -> SessionIdentity:
        if permission not in identity.permissions:
            raise AuthorizationRejected
        return identity

    return dependency


def _tenant(identity: SessionIdentity) -> UUID:
    if identity.organization_id is None:
        raise SessionUnavailable
    return identity.organization_id


def _audit_context(request: Request) -> AuditContext:
    return AuditContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


def _device_response(device: DeviceRecord) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        hostname=device.hostname,
        display_name=device.display_name,
        is_active=device.is_active,
        last_seen_at=device.last_seen_at,
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


def _inventory_response(snapshot: InventorySnapshot) -> InventoryResponse:
    return InventoryResponse(
        device_id=snapshot.device_id,
        hardware=snapshot.hardware,
        software_packages=snapshot.software_packages,
        patches=snapshot.patches,
        services=snapshot.services,
        collected_at=snapshot.collected_at,
        updated_at=snapshot.updated_at,
    )


@devices_router.post("", response_model=DeviceEnrollmentResponse, status_code=201)
async def enroll_device(
    payload: DeviceEnrollmentRequest,
    request: Request,
    response: Response,
    identity: SessionIdentity = Depends(require_mutation_permission("devices:enroll")),
    service: DeviceService = Depends(get_device_service),
) -> DeviceEnrollmentResponse:
    try:
        result: DeviceEnrollmentResult = await service.enroll(
            _tenant(identity),
            identity.user_id,
            DeviceEnrollment(
                hostname=payload.hostname,
                display_name=payload.display_name,
                token_expires_at=payload.token_expires_at,
            ),
            _audit_context(request),
        )
    except DeviceConflict:
        raise HTTPException(status_code=409, detail="Dispositivo ya registrado") from None
    device = _device_response(result.device)
    response.headers["Cache-Control"] = "no-store"
    return DeviceEnrollmentResponse(
        **device.model_dump(),
        token_id=result.token_id,
        token=result.token,
        token_expires_at=result.token_expires_at,
    )


@devices_router.get("", response_model=DeviceListResponse)
async def list_devices(
    identity: SessionIdentity = Depends(require_permission("devices:read")),
    service: DeviceService = Depends(get_device_service),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: UUID | None = None,
) -> DeviceListResponse:
    devices, next_cursor = await service.list_devices(
        _tenant(identity),
        actor_id=identity.user_id,
        assigned_only="devices:read_all" not in identity.permissions,
        limit=limit,
        after_id=after,
    )
    return DeviceListResponse(
        items=tuple(_device_response(device) for device in devices),
        next_cursor=next_cursor,
    )


@devices_router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: UUID,
    identity: SessionIdentity = Depends(require_permission("devices:read")),
    service: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    try:
        device = await service.get_device(
            _tenant(identity),
            device_id,
            actor_id=identity.user_id,
            assigned_only="devices:read_all" not in identity.permissions,
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado") from None
    return _device_response(device)


@devices_router.patch("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: UUID,
    payload: DeviceUpdateRequest,
    request: Request,
    identity: SessionIdentity = Depends(require_mutation_permission("devices:enroll")),
    service: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    try:
        device = await service.update_device(
            _tenant(identity),
            device_id,
            identity.user_id,
            DeviceUpdate(display_name=payload.display_name),
            _audit_context(request),
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado") from None
    return _device_response(device)


@devices_router.delete("/{device_id}", status_code=204)
async def delete_device(
    device_id: UUID,
    request: Request,
    identity: SessionIdentity = Depends(require_mutation_permission("devices:delete")),
    service: DeviceService = Depends(get_device_service),
) -> None:
    try:
        await service.delete_device(
            _tenant(identity), device_id, identity.user_id, _audit_context(request)
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado") from None


@devices_router.post("/{device_id}/tokens", response_model=DeviceTokenResponse, status_code=201)
async def rotate_device_token(
    device_id: UUID,
    payload: TokenRotationRequest,
    request: Request,
    response: Response,
    identity: SessionIdentity = Depends(require_mutation_permission("devices:enroll")),
    service: DeviceService = Depends(get_device_service),
) -> DeviceTokenResponse:
    try:
        result: DeviceTokenResult = await service.rotate_token(
            _tenant(identity),
            device_id,
            identity.user_id,
            expires_at=payload.expires_at,
            audit=_audit_context(request),
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado") from None
    except DeviceConflict:
        raise HTTPException(status_code=409, detail="Rotación de token inválida") from None
    response.headers["Cache-Control"] = "no-store"
    return DeviceTokenResponse(
        token_id=result.token_id,
        token=result.token,
        expires_at=result.expires_at,
    )


@devices_router.delete("/{device_id}/tokens/{token_id}", status_code=204)
async def revoke_device_token(
    device_id: UUID,
    token_id: UUID,
    request: Request,
    identity: SessionIdentity = Depends(require_mutation_permission("devices:enroll")),
    service: DeviceService = Depends(get_device_service),
) -> None:
    try:
        await service.revoke_token(
            _tenant(identity),
            device_id,
            token_id,
            identity.user_id,
            _audit_context(request),
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Dispositivo o token no encontrado") from None


@devices_router.post("/{device_id}/disconnect", status_code=204)
async def disconnect_device(
    device_id: UUID,
    request: Request,
    identity: SessionIdentity = Depends(require_mutation_permission("devices:enroll")),
    service: DeviceService = Depends(get_device_service),
) -> None:
    try:
        await service.rotate_token(
            _tenant(identity),
            device_id,
            identity.user_id,
            expires_at=None,
            audit=_audit_context(request),
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado") from None


@devices_router.post("/{device_id}/assignments", status_code=204)
async def assign_device(
    device_id: UUID,
    payload: DeviceAssignmentRequest,
    request: Request,
    identity: SessionIdentity = Depends(require_mutation_permission("devices:assign")),
    service: DeviceService = Depends(get_device_service),
) -> None:
    try:
        await service.assign_device(
            _tenant(identity),
            device_id,
            payload.user_id,
            identity.user_id,
            _audit_context(request),
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Recurso no encontrado") from None


@devices_router.delete("/{device_id}/assignments/{user_id}", status_code=204)
async def unassign_device(
    device_id: UUID,
    user_id: UUID,
    request: Request,
    identity: SessionIdentity = Depends(require_mutation_permission("devices:assign")),
    service: DeviceService = Depends(get_device_service),
) -> None:
    try:
        await service.unassign_device(
            _tenant(identity),
            device_id,
            user_id,
            identity.user_id,
            _audit_context(request),
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Recurso no encontrado") from None


@devices_router.get("/{device_id}/inventory", response_model=InventoryResponse)
async def get_inventory(
    device_id: UUID,
    identity: SessionIdentity = Depends(require_permission("inventory:read")),
    service: DeviceService = Depends(get_device_service),
) -> InventoryResponse:
    try:
        snapshot = await service.get_inventory(
            _tenant(identity),
            device_id,
            actor_id=identity.user_id,
            assigned_only="inventory:read_all" not in identity.permissions,
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Inventario no encontrado") from None
    return _inventory_response(snapshot)


@devices_router.put("/{device_id}/inventory", response_model=InventoryResponse)
async def write_inventory(
    device_id: UUID,
    payload: InventoryWriteRequest,
    identity: AgentIdentity = Depends(require_agent),
    service: DeviceService = Depends(get_device_service),
) -> InventoryResponse:
    if device_id != identity.device_id:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    snapshot = InventorySnapshotWrite(
        hardware=payload.hardware.model_dump(mode="json"),
        software_packages=tuple(
            item.model_dump(mode="json") for item in payload.software_packages
        ),
        patches=tuple(item.model_dump(mode="json") for item in payload.patches),
        services=tuple(item.model_dump(mode="json") for item in payload.services),
        collected_at=payload.collected_at,
    )
    try:
        result = await service.write_inventory(identity, snapshot)
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado") from None
    except DeviceConflict:
        raise HTTPException(status_code=409, detail="Inventario desactualizado") from None
    return _inventory_response(result)
