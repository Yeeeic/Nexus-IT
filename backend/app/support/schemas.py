"""Strict public schemas and untrusted attachment validation."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


TicketStatus = Literal[
    "NEW",
    "ASSIGNED",
    "IN_PROGRESS",
    "PENDING_CUSTOMER",
    "RESOLVED",
    "CLOSED",
]
TicketPriority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ActionName = Literal[
    "restart_service",
    "flush_dns",
    "collect_extended_diagnostics",
    "reboot_system",
]
AgentActionStatus = Literal[
    "ACCEPTED", "EXECUTING", "SUCCEEDED", "FAILED", "INTERRUPTED", "UNKNOWN"
]

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,100}$")


def _normalize_text(value: str, *, multiline: bool) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    allowed_controls = {"\n", "\r", "\t"} if multiline else set()
    if any(
        unicodedata.category(character) == "Cc"
        and character not in allowed_controls
        for character in normalized
    ):
        raise ValueError("El texto contiene caracteres de control")
    return normalized


def _normalize_required_text(value: str, *, multiline: bool) -> str:
    normalized = _normalize_text(value, multiline=multiline)
    if not normalized:
        raise ValueError("El texto no puede estar vacío")
    return normalized


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RestartServiceParameters(_ClosedModel):
    service_name: str = Field(min_length=1, max_length=100)

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        normalized = _normalize_text(value, multiline=False)
        if _SERVICE_NAME.fullmatch(normalized) is None:
            raise ValueError("Nombre de servicio inválido")
        return normalized


class FlushDnsParameters(_ClosedModel):
    pass


class DiagnosticsParameters(_ClosedModel):
    include_logs: bool = False
    max_log_lines: int = Field(default=1000, ge=1, le=10_000)


class RebootSystemParameters(_ClosedModel):
    delay_seconds: int = Field(default=0, ge=0, le=300)
    force: bool = False


_ACTION_PARAMETER_MODELS: dict[str, type[_ClosedModel]] = {
    "restart_service": RestartServiceParameters,
    "flush_dns": FlushDnsParameters,
    "collect_extended_diagnostics": DiagnosticsParameters,
    "reboot_system": RebootSystemParameters,
}


class ActionRequest(_ClosedModel):
    action_name: ActionName
    parameters: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_parameters(self) -> ActionRequest:
        model = _ACTION_PARAMETER_MODELS[self.action_name]
        validated = model.model_validate(self.parameters)
        self.parameters = validated.model_dump(mode="json")
        return self

    @property
    def canonical_parameters(self) -> str:
        return json.dumps(
            self.parameters,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


class TicketCreate(_ClosedModel):
    device_id: UUID | None = None
    alert_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10_000)
    priority: TicketPriority = "MEDIUM"

    @field_validator("device_id", "alert_id", mode="before")
    @classmethod
    def parse_optional_uuid(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return _normalize_required_text(value, multiline=False)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return _normalize_required_text(value, multiline=True)


class CommentCreate(_ClosedModel):
    content: str = Field(min_length=1, max_length=10_000)
    is_internal: bool = False

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return _normalize_required_text(value, multiline=True)


class TicketTransition(_ClosedModel):
    expected_status: TicketStatus
    status: TicketStatus
    assigned_to: UUID | None = None

    @field_validator("assigned_to", mode="before")
    @classmethod
    def parse_assignee(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value


class ActionResultCreate(_ClosedModel):
    status: AgentActionStatus
    exit_code: int | None = Field(default=None, ge=-(2**31), le=2**31 - 1)
    output_summary: str | None = Field(default=None, max_length=2_000)

    @field_validator("output_summary")
    @classmethod
    def normalize_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_text(value, multiline=True)


@dataclass(frozen=True, slots=True)
class AttachmentMetadata:
    original_name: str
    stored_filename: str
    mime_type: str
    file_size: int


_MAGIC_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"%PDF-", "application/pdf", ".pdf"),
)


def validate_attachment(*, original_name: str, content: bytes) -> AttachmentMetadata:
    """Validate bytes and return metadata; never persists untrusted content."""
    if not content:
        raise ValueError("Archivo vacío")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError("El archivo excede 10 MB")
    name = _normalize_text(original_name, multiline=False)
    if (
        not name
        or len(name) > 255
        or name != PurePath(name).name
        or "/" in name
        or "\\" in name
    ):
        raise ValueError("Nombre de archivo inválido")
    name = "".join(
        character
        if character.isalnum() or character in {".", "_", "-", " "}
        else "_"
        for character in name
    ).strip(" .")
    if not name:
        name = "attachment"
    name = name[:255]
    detected = next(
        (
            (mime_type, extension)
            for magic, mime_type, extension in _MAGIC_TYPES
            if content.startswith(magic)
        ),
        None,
    )
    if detected is None:
        raise ValueError("Tipo de archivo no permitido")
    mime_type, extension = detected
    return AttachmentMetadata(
        original_name=name,
        stored_filename=f"{uuid4()}{extension}",
        mime_type=mime_type,
        file_size=len(content),
    )
