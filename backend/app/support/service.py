"""Help desk state machine and allowlisted remote action orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import UUID, uuid4

from backend.app.support.schemas import (
    ActionRequest,
    ActionResultCreate,
    CommentCreate,
    TicketCreate,
    TicketStatus,
    validate_attachment,
)


class SupportNotFound(Exception):
    pass


class SupportConflict(Exception):
    pass


class SupportUnavailable(Exception):
    pass


class SupportInvalid(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RequestTrace:
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class ActionCommand:
    organization_id: UUID
    id: UUID
    device_id: UUID
    action_name: str
    requested_by: UUID
    nonce: UUID
    key_version: int | None
    issued_at: datetime
    expires_at: datetime
    signature: str | None
    parameters: dict[str, object]
    parameters_canonical: str
    status: str
    trace: RequestTrace


@dataclass(frozen=True, slots=True)
class TicketTransitionCommand:
    organization_id: UUID
    ticket_id: UUID
    actor_id: UUID
    expected_status: TicketStatus
    target_status: TicketStatus
    assigned_to: UUID | None
    resolved_at: datetime | None
    trace: RequestTrace


@dataclass(frozen=True, slots=True)
class ActionResult:
    status: str
    is_replay: bool


@dataclass(frozen=True, slots=True)
class ActionAcknowledgement:
    status: str
    is_replay: bool


@dataclass(frozen=True, slots=True)
class AttachmentRecord:
    id: UUID
    ticket_id: UUID
    original_name: str
    stored_filename: str
    mime_type: str
    file_size: int
    storage_path: str
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class AttachmentCreateCommand:
    organization_id: UUID
    id: UUID
    ticket_id: UUID
    actor_id: UUID
    original_name: str
    stored_filename: str
    mime_type: str
    file_size: int
    storage_path: str
    owner_only: bool
    trace: RequestTrace


@dataclass(frozen=True, slots=True)
class AttachmentDownload:
    original_name: str
    mime_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class TicketRecord:
    id: UUID
    device_id: UUID | None
    alert_id: UUID | None
    created_by: UUID
    assigned_to: UUID | None
    ticket_number: str
    title: str
    description: str
    status: TicketStatus
    priority: str
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TicketCreateCommand:
    organization_id: UUID
    id: UUID
    device_id: UUID | None
    alert_id: UUID | None
    created_by: UUID
    ticket_number: str
    title: str
    description: str
    priority: str
    trace: RequestTrace


@dataclass(frozen=True, slots=True)
class CommentRecord:
    id: UUID
    ticket_id: UUID
    user_id: UUID
    is_internal: bool
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CommentCreateCommand:
    organization_id: UUID
    id: UUID
    ticket_id: UUID
    user_id: UUID
    is_internal: bool
    content: str
    owner_only: bool
    trace: RequestTrace


@dataclass(frozen=True, slots=True)
class ActionApproval:
    action_id: UUID
    status: str


@dataclass(frozen=True, slots=True)
class AttachmentDeletionOutboxItem:
    id: UUID
    organization_id: UUID
    storage_path: str
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime


class ActionSigner(Protocol):
    key_version: int

    def sign(self, payload: bytes) -> str: ...


class AttachmentStorage(Protocol):
    async def store(self, **values: object) -> str: ...

    async def read(self, relative_path: str) -> bytes: ...

    async def delete(self, relative_path: str) -> None: ...


class SupportRepository(Protocol):
    async def create_ticket(self, command: TicketCreateCommand) -> TicketRecord: ...

    async def list_tickets(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        can_read_all: bool,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[TicketRecord, ...], UUID | None]: ...

    async def get_ticket(
        self,
        organization_id: UUID,
        ticket_id: UUID,
        *,
        actor_id: UUID,
        can_read_all: bool,
    ) -> TicketRecord: ...

    async def delete_ticket(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        actor_id: UUID,
        can_delete_any: bool,
        trace: RequestTrace,
    ) -> tuple[str, ...]: ...

    async def add_comment(self, command: CommentCreateCommand) -> CommentRecord: ...

    async def list_comments(
        self,
        organization_id: UUID,
        ticket_id: UUID,
        *,
        actor_id: UUID,
        include_internal: bool,
        can_read_all: bool,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[CommentRecord, ...], UUID | None]: ...

    async def create_action(self, command: ActionCommand) -> ActionCommand: ...

    async def transition_ticket(
        self, command: TicketTransitionCommand
    ) -> TicketTransitionCommand: ...

    async def record_action_result(self, **values: object) -> bool: ...

    async def poll_actions(
        self,
        organization_id: UUID,
        device_id: UUID,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[ActionCommand, ...]: ...

    async def acknowledge_action(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        action_id: UUID,
        token_id: UUID,
        now: datetime,
        trace: RequestTrace,
    ) -> bool: ...

    async def approve_action(
        self,
        *,
        organization_id: UUID,
        action_id: UUID,
        approver_id: UUID,
        now: datetime,
        signer: ActionSigner,
        trace: RequestTrace,
    ) -> ActionApproval: ...

    async def create_attachment(
        self, command: AttachmentCreateCommand
    ) -> AttachmentRecord: ...

    async def get_attachment(
        self,
        organization_id: UUID,
        ticket_id: UUID,
        attachment_id: UUID,
        *,
        actor_id: UUID,
        can_read_all: bool,
    ) -> AttachmentRecord: ...

    async def delete_attachment(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        attachment_id: UUID,
        actor_id: UUID,
        owner_only: bool,
        expected_storage_path: str,
        trace: RequestTrace,
    ) -> None: ...

    async def claim_pending_attachment_deletions(
        self,
        organization_id: UUID,
        *,
        batch_size: int = 20,
    ) -> tuple[AttachmentDeletionOutboxItem, ...]: ...

    async def mark_attachment_deletion_completed(
        self,
        organization_id: UUID,
        outbox_id: UUID,
    ) -> None: ...

    async def mark_attachment_deletion_failed(
        self,
        organization_id: UUID,
        outbox_id: UUID,
        error_summary: str,
    ) -> None: ...


_TICKET_TRANSITIONS: dict[str, frozenset[str]] = {
    "NEW": frozenset({"ASSIGNED"}),
    "ASSIGNED": frozenset({"IN_PROGRESS"}),
    "IN_PROGRESS": frozenset({"PENDING_CUSTOMER", "RESOLVED"}),
    "PENDING_CUSTOMER": frozenset({"IN_PROGRESS"}),
    "RESOLVED": frozenset({"CLOSED", "IN_PROGRESS"}),
    "CLOSED": frozenset(),
}
_RESULT_STATUS = {
    "ACCEPTED": "ACCEPTED",
    "EXECUTING": "EXECUTING",
    "SUCCEEDED": "COMPLETED",
    "FAILED": "FAILED",
    "INTERRUPTED": "INTERRUPTED",
    "UNKNOWN": "UNKNOWN",
}


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Timestamp sin zona horaria")
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def build_action_signing_payload(command: ActionCommand) -> bytes:
    if command.key_version is None:
        raise ValueError("La acción no tiene versión de clave")
    fields = (
        "nexus-action:v1",
        str(command.id),
        str(command.organization_id),
        str(command.device_id),
        command.action_name,
        str(command.nonce),
        str(command.key_version),
        _utc_timestamp(command.issued_at),
        _utc_timestamp(command.expires_at),
        command.parameters_canonical,
    )
    return "\n".join(fields).encode("utf-8")


def _result_digest(result: ActionResultCreate) -> bytes:
    canonical = json.dumps(
        result.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).digest()


class SupportService:
    def __init__(
        self,
        *,
        repository: SupportRepository,
        signer: ActionSigner,
        attachment_storage: AttachmentStorage | None = None,
        clock: Callable[[], datetime],
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._signer = signer
        self._attachment_storage = attachment_storage
        self._clock = clock
        self._uuid_factory = uuid_factory

    def _storage(self) -> AttachmentStorage:
        if self._attachment_storage is None:
            raise SupportUnavailable
        return self._attachment_storage

    async def upload_attachment(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        actor_id: UUID,
        original_name: str,
        content: bytes,
        owner_only: bool,
        trace: RequestTrace,
    ) -> AttachmentRecord:
        try:
            metadata = validate_attachment(
                original_name=original_name, content=content
            )
        except ValueError:
            raise SupportInvalid from None
        attachment_id = self._uuid_factory()
        if attachment_id.version != 4:
            raise SupportUnavailable
        storage = self._storage()
        storage_path = await storage.store(
            organization_id=str(organization_id),
            ticket_id=str(ticket_id),
            metadata=metadata,
            content=content,
        )
        command = AttachmentCreateCommand(
            organization_id=organization_id,
            id=attachment_id,
            ticket_id=ticket_id,
            actor_id=actor_id,
            original_name=metadata.original_name,
            stored_filename=metadata.stored_filename,
            mime_type=metadata.mime_type,
            file_size=metadata.file_size,
            storage_path=storage_path,
            owner_only=owner_only,
            trace=trace,
        )
        try:
            return await self._repository.create_attachment(command)
        except Exception:
            await storage.delete(storage_path)
            raise

    async def download_attachment(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        attachment_id: UUID,
        actor_id: UUID,
        can_read_all: bool,
    ) -> AttachmentDownload:
        record = await self._repository.get_attachment(
            organization_id,
            ticket_id,
            attachment_id,
            actor_id=actor_id,
            can_read_all=can_read_all,
        )
        try:
            content = await self._storage().read(record.storage_path)
        except (FileNotFoundError, ValueError):
            raise SupportNotFound from None
        return AttachmentDownload(
            original_name=record.original_name,
            mime_type=record.mime_type,
            content=content,
        )

    async def delete_attachment(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        attachment_id: UUID,
        actor_id: UUID,
        owner_only: bool,
        trace: RequestTrace,
    ) -> None:
        record = await self._repository.get_attachment(
            organization_id,
            ticket_id,
            attachment_id,
            actor_id=actor_id,
            can_read_all=not owner_only,
        )
        await self._repository.delete_attachment(
            organization_id=organization_id,
            ticket_id=ticket_id,
            attachment_id=attachment_id,
            actor_id=actor_id,
            owner_only=owner_only,
            expected_storage_path=record.storage_path,
            trace=trace,
        )
        if self._attachment_storage is not None:
            try:
                await self._attachment_storage.delete(record.storage_path)
            except Exception:
                pass  # Outbox worker guarantees idempotent retries

    async def create_ticket(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        request: TicketCreate,
        trace: RequestTrace,
    ) -> TicketRecord:
        ticket_id = self._uuid_factory()
        if ticket_id.version != 4:
            raise SupportUnavailable
        command = TicketCreateCommand(
            organization_id=organization_id,
            id=ticket_id,
            device_id=request.device_id,
            alert_id=request.alert_id,
            created_by=actor_id,
            ticket_number=f"NEX-{ticket_id.hex[:12].upper()}",
            title=request.title,
            description=request.description,
            priority=request.priority,
            trace=trace,
        )
        return await self._repository.create_ticket(command)

    async def list_tickets(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        can_read_all: bool,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[TicketRecord, ...], UUID | None]:
        return await self._repository.list_tickets(
            organization_id,
            actor_id=actor_id,
            can_read_all=can_read_all,
            limit=limit,
            after_id=after_id,
        )

    async def get_ticket(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        actor_id: UUID,
        can_read_all: bool,
    ) -> TicketRecord:
        return await self._repository.get_ticket(
            organization_id,
            ticket_id,
            actor_id=actor_id,
            can_read_all=can_read_all,
        )

    async def delete_ticket(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        actor_id: UUID,
        can_delete_any: bool,
        trace: RequestTrace,
    ) -> None:
        storage_paths = await self._repository.delete_ticket(
            organization_id=organization_id,
            ticket_id=ticket_id,
            actor_id=actor_id,
            can_delete_any=can_delete_any,
            trace=trace,
        )
        if storage_paths and self._attachment_storage is not None:
            for storage_path in storage_paths:
                try:
                    await self._attachment_storage.delete(storage_path)
                except Exception:
                    pass  # Outbox worker guarantees idempotent retries

    async def process_pending_attachment_deletions(
        self,
        organization_id: UUID,
        *,
        batch_size: int = 20,
    ) -> int:
        storage = self._storage()
        claimed = await self._repository.claim_pending_attachment_deletions(
            organization_id,
            batch_size=batch_size,
        )
        processed = 0
        for item in claimed:
            try:
                await storage.delete(item.storage_path)
                await self._repository.mark_attachment_deletion_completed(
                    organization_id,
                    item.id,
                )
                processed += 1
            except Exception as error:
                await self._repository.mark_attachment_deletion_failed(
                    organization_id,
                    item.id,
                    str(error),
                )
        return processed

    async def add_comment(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        actor_id: UUID,
        request: CommentCreate,
        owner_only: bool,
        trace: RequestTrace,
    ) -> CommentRecord:
        comment_id = self._uuid_factory()
        if comment_id.version != 4:
            raise SupportUnavailable
        return await self._repository.add_comment(
            CommentCreateCommand(
                organization_id=organization_id,
                id=comment_id,
                ticket_id=ticket_id,
                user_id=actor_id,
                is_internal=request.is_internal,
                content=request.content,
                owner_only=owner_only,
                trace=trace,
            )
        )

    async def list_comments(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        actor_id: UUID,
        include_internal: bool,
        can_read_all: bool,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[CommentRecord, ...], UUID | None]:
        return await self._repository.list_comments(
            organization_id,
            ticket_id,
            actor_id=actor_id,
            include_internal=include_internal,
            can_read_all=can_read_all,
            limit=limit,
            after_id=after_id,
        )

    async def request_action(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        request: ActionRequest,
        trace: RequestTrace,
    ) -> ActionCommand:
        issued_at = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        action_id = self._uuid_factory()
        nonce = self._uuid_factory()
        if action_id.version != 4 or nonce.version != 4:
            raise SupportUnavailable
        requires_approval = request.action_name == "reboot_system"
        unsigned = ActionCommand(
            organization_id=organization_id,
            id=action_id,
            device_id=device_id,
            action_name=request.action_name,
            requested_by=actor_id,
            nonce=nonce,
            key_version=None if requires_approval else self._signer.key_version,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(minutes=5),
            signature=None,
            parameters=dict(request.parameters),
            parameters_canonical=request.canonical_parameters,
            status=(
                "PENDING_APPROVAL" if requires_approval else "DISPATCHED"
            ),
            trace=trace,
        )
        command = unsigned
        if not requires_approval:
            command = replace(
                unsigned,
                signature=self._signer.sign(build_action_signing_payload(unsigned)),
            )
        return await self._repository.create_action(command)

    async def approve_action(
        self,
        *,
        organization_id: UUID,
        action_id: UUID,
        approver_id: UUID,
        trace: RequestTrace,
    ) -> ActionApproval:
        return await self._repository.approve_action(
            organization_id=organization_id,
            action_id=action_id,
            approver_id=approver_id,
            now=self._clock(),
            signer=self._signer,
            trace=trace,
        )

    async def poll_actions(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        limit: int,
    ) -> tuple[ActionCommand, ...]:
        return await self._repository.poll_actions(
            organization_id,
            device_id,
            now=self._clock(),
            limit=limit,
        )

    async def acknowledge_action(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        action_id: UUID,
        token_id: UUID,
        trace: RequestTrace,
    ) -> ActionAcknowledgement:
        replay = await self._repository.acknowledge_action(
            organization_id=organization_id,
            device_id=device_id,
            action_id=action_id,
            token_id=token_id,
            now=self._clock(),
            trace=trace,
        )
        return ActionAcknowledgement(status="ACCEPTED", is_replay=replay)

    async def transition_ticket(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        actor_id: UUID,
        expected_status: TicketStatus,
        target_status: TicketStatus,
        assigned_to: UUID | None,
        trace: RequestTrace,
    ) -> TicketTransitionCommand:
        if target_status not in _TICKET_TRANSITIONS[expected_status]:
            raise SupportConflict("Transición de ticket inválida")
        if target_status == "ASSIGNED" and assigned_to is None:
            raise SupportConflict("La asignación requiere técnico")
        if target_status != "ASSIGNED" and assigned_to is not None:
            raise SupportConflict("Asignación no permitida en esta transición")
        command = TicketTransitionCommand(
            organization_id=organization_id,
            ticket_id=ticket_id,
            actor_id=actor_id,
            expected_status=expected_status,
            target_status=target_status,
            assigned_to=assigned_to,
            resolved_at=self._clock() if target_status == "RESOLVED" else None,
            trace=trace,
        )
        return await self._repository.transition_ticket(command)

    async def record_action_result(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        action_id: UUID,
        token_id: UUID,
        result: ActionResultCreate,
        trace: RequestTrace,
    ) -> ActionResult:
        mapped_status = _RESULT_STATUS[result.status]
        replay = await self._repository.record_action_result(
            organization_id=organization_id,
            device_id=device_id,
            action_id=action_id,
            token_id=token_id,
            status=mapped_status,
            exit_code=result.exit_code,
            output_summary=result.output_summary,
            result_digest=_result_digest(result),
            executed_at=self._clock(),
            trace=trace,
        )
        return ActionResult(status=mapped_status, is_replay=replay)
