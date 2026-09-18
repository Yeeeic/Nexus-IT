"""Versioned tenant user administration endpoints."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from backend.app.api.dependencies import require_permission
from backend.app.auth.passwords import hash_password
from backend.app.auth.session import SessionIdentity, SessionUnavailable
from backend.app.users.service import UserDirectory


users_router = APIRouter(prefix="/users", tags=["users"])


class UserSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    full_name: str
    is_active: bool


class UserListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[UserSummaryResponse, ...]
    next_cursor: UUID | None


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=150)
    password: SecretStr = Field(min_length=12, max_length=1024)
    role: str = Field(default="READER", pattern=r"^(ADMIN|TECHNICIAN|READER)$")

    @field_validator("email", "full_name", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if not any(character.isalpha() for character in password):
            raise ValueError("password must contain a letter")
        if not any(character.isdigit() for character in password):
            raise ValueError("password must contain a digit")
        return value


class UserStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    is_active: bool


def get_user_directory(request: Request) -> UserDirectory:
    directory = getattr(request.app.state, "user_directory", None)
    if directory is None:
        raise SessionUnavailable
    return cast(UserDirectory, directory)


@users_router.get("", response_model=UserListResponse)
async def list_users(
    identity: SessionIdentity = Depends(require_permission("users:manage")),
    directory: UserDirectory = Depends(get_user_directory),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: UUID | None = None,
) -> UserListResponse:
    organization_id = identity.organization_id
    if organization_id is None:
        raise SessionUnavailable
    users, next_cursor = await directory.list_users(
        organization_id,
        actor_id=identity.user_id,
        limit=limit,
        after_id=after,
    )
    return UserListResponse(
        items=tuple(
            UserSummaryResponse(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                is_active=user.is_active,
            )
            for user in users
        ),
        next_cursor=next_cursor,
    )


@users_router.post("", response_model=UserSummaryResponse, status_code=201)
async def create_user(
    request: Request,
    payload: UserCreateRequest,
    identity: SessionIdentity = Depends(require_permission("users:manage", csrf=True)),
    directory: UserDirectory = Depends(get_user_directory),
) -> UserSummaryResponse:
    organization_id = identity.organization_id
    if organization_id is None:
        raise SessionUnavailable

    hashed = hash_password(payload.password.get_secret_value())
    user = await directory.create_user(
        organization_id,
        actor_id=identity.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hashed,
        role_name=payload.role,
    )
    return UserSummaryResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
    )


@users_router.patch("/{user_id}/status", response_model=UserSummaryResponse)
async def toggle_user_status(
    request: Request,
    user_id: UUID,
    payload: UserStatusRequest,
    identity: SessionIdentity = Depends(require_permission("users:manage", csrf=True)),
    directory: UserDirectory = Depends(get_user_directory),
) -> UserSummaryResponse:
    organization_id = identity.organization_id
    if organization_id is None:
        raise SessionUnavailable

    user = await directory.toggle_user_active(
        organization_id,
        actor_id=identity.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        user_id=user_id,
        is_active=payload.is_active,
    )
    return UserSummaryResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
    )


@users_router.post("/{user_id}/revoke-sessions")
async def revoke_user_sessions(
    request: Request,
    user_id: UUID,
    identity: SessionIdentity = Depends(require_permission("users:manage", csrf=True)),
    directory: UserDirectory = Depends(get_user_directory),
) -> dict[str, object]:
    organization_id = identity.organization_id
    if organization_id is None:
        raise SessionUnavailable

    count = await directory.revoke_user_sessions(
        organization_id,
        actor_id=identity.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        user_id=user_id,
    )
    return {"revoked_sessions": count, "user_id": str(user_id)}


@users_router.delete("/{user_id}", status_code=204)
async def delete_user(
    request: Request,
    user_id: UUID,
    identity: SessionIdentity = Depends(require_permission("users:manage", csrf=True)),
    directory: UserDirectory = Depends(get_user_directory),
) -> None:
    organization_id = identity.organization_id
    if organization_id is None:
        raise SessionUnavailable

    if user_id == identity.user_id:
        raise HTTPException(
            status_code=400,
            detail="No puedes eliminar tu propio usuario administrador",
        )

    await directory.delete_user(
        organization_id,
        actor_id=identity.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        user_id=user_id,
    )
