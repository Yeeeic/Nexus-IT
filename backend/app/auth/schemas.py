"""Strict public contracts for authentication endpoints."""

from typing import Annotated, Any, Literal
import unicodedata
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


Email = Annotated[str, Field(min_length=3, max_length=255)]


def normalize_email(email: str) -> str:
    """Apply canonical normalization required before email lookup or storage."""
    return unicodedata.normalize("NFC", email.strip()).lower()


def _is_valid_email(email: str) -> bool:
    if email.count("@") != 1 or any(character.isspace() for character in email):
        return False
    local_part, domain = email.split("@")
    return bool(
        local_part
        and domain
        and len(local_part) <= 64
        and "." in domain
        and not local_part.startswith(".")
        and not local_part.endswith(".")
        and not domain.startswith(".")
        and not domain.endswith(".")
        and ".." not in local_part
        and ".." not in domain
    )


class LoginRequest(BaseModel):
    """Untrusted login input accepted by ``POST /api/v1/auth/login``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    email: Email
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalize_email(value)
        return value

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, value: str) -> str:
        if not _is_valid_email(value):
            raise ValueError("invalid email format")
        return value


class LoginOrganization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str = Field(min_length=1, max_length=150)


class LoginResponse(BaseModel):
    """Public login output; session secrets are cookies, never response fields."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["AUTHENTICATED", "ORGANIZATION_SELECTION_REQUIRED"]
    organizations: tuple[LoginOrganization, ...]


class ContextSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    organization_id: UUID

    @field_validator("organization_id", mode="before")
    @classmethod
    def parse_organization_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            return UUID(value)
        return value


class ContextSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["AUTHENTICATED"] = "AUTHENTICATED"


class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["SIGNED_OUT"] = "SIGNED_OUT"


class PasswordResetConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    token: SecretStr = Field(min_length=3, max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=1024)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if not any(character.isalpha() for character in password):
            raise ValueError("password must contain a letter")
        if not any(character.isdigit() for character in password):
            raise ValueError("password must contain a digit")
        return value


class PasswordResetConfirmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["PASSWORD_RESET_COMPLETE"] = "PASSWORD_RESET_COMPLETE"


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    email: Email

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalize_email(value)
        return value

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, value: str) -> str:
        if not _is_valid_email(value):
            raise ValueError("invalid email format")
        return value


class PasswordResetRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["PASSWORD_RESET_REQUEST_ACCEPTED"] = (
        "PASSWORD_RESET_REQUEST_ACCEPTED"
    )


class UserMeResponse(BaseModel):
    """Explicit public output for authenticated user session context."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    email: Email
    full_name: str = Field(min_length=1, max_length=150)
    organization_id: UUID | None = None
    permissions: tuple[str, ...] = ()
    available_organizations: tuple[LoginOrganization, ...] = ()
