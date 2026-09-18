import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.app.support.schemas import ActionRequest, ActionResultCreate
from backend.app.support.service import (
    ActionCommand,
    AttachmentCreateCommand,
    AttachmentRecord,
    RequestTrace,
    SupportConflict,
    SupportService,
    TicketTransitionCommand,
    build_action_signing_payload,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
DEVICE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ACTION_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
NONCE = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
TICKET_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
NOW = datetime(2026, 8, 24, 18, 30, tzinfo=timezone.utc)


class Signer:
    key_version = 2

    def __init__(self) -> None:
        self.payload: bytes | None = None

    def sign(self, payload: bytes) -> str:
        self.payload = payload
        return "signature-base64"


class Repository:
    def __init__(self) -> None:
        self.action: ActionCommand | None = None
        self.transition: TicketTransitionCommand | None = None
        self.result_calls = 0
        self.attachment: AttachmentCreateCommand | None = None

    async def create_action(self, command: ActionCommand) -> ActionCommand:
        self.action = command
        return command

    async def transition_ticket(
        self, command: TicketTransitionCommand
    ) -> TicketTransitionCommand:
        self.transition = command
        return command

    async def record_action_result(self, **_values: object) -> bool:
        self.result_calls += 1
        return self.result_calls > 1

    async def create_attachment(
        self, command: AttachmentCreateCommand
    ) -> AttachmentRecord:
        self.attachment = command
        return AttachmentRecord(
            id=command.id,
            ticket_id=command.ticket_id,
            original_name=command.original_name,
            stored_filename=command.stored_filename,
            mime_type=command.mime_type,
            file_size=command.file_size,
            storage_path=command.storage_path,
            uploaded_at=NOW,
        )

    async def delete_ticket(self, **kwargs: object) -> tuple[str, ...]:
        self.deleted_ticket_kwargs = kwargs
        return ("private/one.png", "private/two.txt")


class AttachmentStorage:
    def __init__(self) -> None:
        self.path: str | None = None
        self.deleted_paths: list[str] = []

    async def store(self, **values: object) -> str:
        metadata = values["metadata"]
        self.path = f"private/{metadata.stored_filename}"
        return self.path

    async def read(self, _relative_path: str) -> bytes:
        return b"content"

    async def delete(self, relative_path: str) -> None:
        self.deleted_paths.append(relative_path)


def make_service(repository: Repository, signer: Signer) -> SupportService:
    ids = iter((ACTION_ID, NONCE))
    return SupportService(
        repository=repository,
        signer=signer,
        clock=lambda: NOW,
        uuid_factory=lambda: next(ids),
    )


def test_reboot_action_waits_for_admin_approval_before_signing() -> None:
    repository = Repository()
    signer = Signer()
    service = make_service(repository, signer)

    action = asyncio.run(
        service.request_action(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            actor_id=USER_ID,
            request=ActionRequest(
                action_name="reboot_system",
                parameters={"delay_seconds": 30, "force": False},
            ),
            trace=RequestTrace(ip_address="192.0.2.1", user_agent="test"),
        )
    )

    assert action.status == "PENDING_APPROVAL"
    assert action.expires_at.isoformat() == "2026-08-24T18:35:00+00:00"
    assert action.signature is None
    assert action.key_version is None
    assert signer.payload is None


def test_non_privileged_action_is_signed_before_dispatch() -> None:
    repository = Repository()
    signer = Signer()
    service = make_service(repository, signer)

    action = asyncio.run(
        service.request_action(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            actor_id=USER_ID,
            request=ActionRequest(action_name="flush_dns", parameters={}),
            trace=RequestTrace(None, None),
        )
    )

    assert action.status == "DISPATCHED"
    assert action.signature == "signature-base64"
    assert action.key_version == 2
    assert signer.payload == build_action_signing_payload(action)


def test_ticket_state_machine_rejects_invalid_transition_before_repository() -> None:
    repository = Repository()
    service = make_service(repository, Signer())

    with pytest.raises(SupportConflict):
        asyncio.run(
            service.transition_ticket(
                organization_id=ORG_ID,
                ticket_id=TICKET_ID,
                actor_id=USER_ID,
                expected_status="NEW",
                target_status="RESOLVED",
                assigned_to=None,
                trace=RequestTrace(None, None),
            )
        )

    assert repository.transition is None


def test_action_result_replay_is_idempotent() -> None:
    repository = Repository()
    service = make_service(repository, Signer())
    result = ActionResultCreate(status="SUCCEEDED", exit_code=0, output_summary="ok")

    first = asyncio.run(
        service.record_action_result(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            action_id=ACTION_ID,
            token_id=NONCE,
            result=result,
            trace=RequestTrace("192.0.2.2", "agent"),
        )
    )
    replay = asyncio.run(
        service.record_action_result(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            action_id=ACTION_ID,
            token_id=NONCE,
            result=result,
            trace=RequestTrace("192.0.2.2", "agent"),
        )
    )

    assert first.is_replay is False
    assert replay.is_replay is True


def test_attachment_upload_validates_bytes_before_persisting_metadata() -> None:
    repository = Repository()
    storage = AttachmentStorage()
    service = SupportService(
        repository=repository,
        signer=Signer(),
        attachment_storage=storage,
        clock=lambda: NOW,
        uuid_factory=lambda: ACTION_ID,
    )

    attachment = asyncio.run(
        service.upload_attachment(
            organization_id=ORG_ID,
            ticket_id=TICKET_ID,
            actor_id=USER_ID,
            original_name="screen.png",
            content=b"\x89PNG\r\n\x1a\ncontent",
            owner_only=True,
            trace=RequestTrace(None, None),
        )
    )

    assert attachment.mime_type == "image/png"
    assert repository.attachment is not None
    assert repository.attachment.storage_path.startswith("private/")
    assert repository.attachment.owner_only is True


def test_delete_ticket_delegates_to_repository() -> None:
    repository = Repository()
    storage = AttachmentStorage()
    service = SupportService(
        repository=repository,
        signer=Signer(),
        attachment_storage=storage,
        clock=lambda: NOW,
        uuid_factory=lambda: ACTION_ID,
    )

    asyncio.run(
        service.delete_ticket(
            organization_id=ORG_ID,
            ticket_id=TICKET_ID,
            actor_id=USER_ID,
            can_delete_any=True,
            trace=RequestTrace(None, None),
        )
    )

    assert repository.deleted_ticket_kwargs["ticket_id"] == TICKET_ID
    assert repository.deleted_ticket_kwargs["organization_id"] == ORG_ID
    assert repository.deleted_ticket_kwargs["can_delete_any"] is True
    assert storage.deleted_paths == ["private/one.png", "private/two.txt"]
