import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4
import pytest

from backend.app.support.service import (
    AttachmentDeletionOutboxItem,
    AttachmentRecord,
    RequestTrace,
    SupportService,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
TICKET_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
ATTACHMENT_ID = UUID("11111111-2222-4333-8444-555555555555")
OUTBOX_ID = UUID("66666666-7777-4888-8999-000000000000")
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


class DummySigner:
    key_version = 1

    def sign(self, payload: bytes) -> str:
        return "sig"


class DummyStorage:
    def __init__(self, should_fail: bool = False) -> None:
        self.deleted_paths: list[str] = []
        self.should_fail = should_fail

    async def store(self, **values: object) -> str:
        return "private/test.png"

    async def read(self, relative_path: str) -> bytes:
        return b"content"

    async def delete(self, relative_path: str) -> None:
        if self.should_fail:
            raise OSError("Disk I/O error during deletion")
        self.deleted_paths.append(relative_path)


class FakeSupportRepository:
    def __init__(self) -> None:
        self.outbox_items: list[AttachmentDeletionOutboxItem] = []
        self.completed_ids: list[UUID] = []
        self.failed_ids: list[tuple[UUID, str]] = []
        self.ticket_deleted = False
        self.attachment_deleted = False

    async def get_attachment(
        self,
        organization_id: UUID,
        ticket_id: UUID,
        attachment_id: UUID,
        *,
        actor_id: UUID,
        can_read_all: bool,
    ) -> AttachmentRecord:
        return AttachmentRecord(
            id=attachment_id,
            ticket_id=ticket_id,
            original_name="test.png",
            stored_filename="test.png",
            mime_type="image/png",
            file_size=100,
            storage_path="private/test.png",
            uploaded_at=NOW,
        )

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
    ) -> None:
        self.attachment_deleted = True
        self.outbox_items.append(
            AttachmentDeletionOutboxItem(
                id=OUTBOX_ID,
                organization_id=organization_id,
                storage_path=expected_storage_path,
                status="PENDING",
                attempts=0,
                max_attempts=5,
                created_at=NOW,
            )
        )

    async def delete_ticket(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        actor_id: UUID,
        can_delete_any: bool,
        trace: RequestTrace,
    ) -> tuple[str, ...]:
        self.ticket_deleted = True
        self.outbox_items.append(
            AttachmentDeletionOutboxItem(
                id=OUTBOX_ID,
                organization_id=organization_id,
                storage_path="private/ticket_attachment.png",
                status="PENDING",
                attempts=0,
                max_attempts=5,
                created_at=NOW,
            )
        )
        return ("private/ticket_attachment.png",)

    async def claim_pending_attachment_deletions(
        self,
        organization_id: UUID,
        *,
        batch_size: int = 20,
    ) -> tuple[AttachmentDeletionOutboxItem, ...]:
        claimed = [
            item for item in self.outbox_items
            if item.organization_id == organization_id and item.status in ("PENDING", "FAILED")
        ][:batch_size]
        return tuple(claimed)

    async def mark_attachment_deletion_completed(
        self,
        organization_id: UUID,
        outbox_id: UUID,
    ) -> None:
        self.completed_ids.append(outbox_id)
        self.outbox_items = [
            AttachmentDeletionOutboxItem(
                id=item.id,
                organization_id=item.organization_id,
                storage_path=item.storage_path,
                status="COMPLETED",
                attempts=item.attempts,
                max_attempts=item.max_attempts,
                created_at=item.created_at,
            )
            if item.id == outbox_id else item
            for item in self.outbox_items
        ]

    async def mark_attachment_deletion_failed(
        self,
        organization_id: UUID,
        outbox_id: UUID,
        error_summary: str,
    ) -> None:
        self.failed_ids.append((outbox_id, error_summary))
        self.outbox_items = [
            AttachmentDeletionOutboxItem(
                id=item.id,
                organization_id=item.organization_id,
                storage_path=item.storage_path,
                status="FAILED" if item.attempts + 1 >= item.max_attempts else "PENDING",
                attempts=item.attempts + 1,
                max_attempts=item.max_attempts,
                created_at=item.created_at,
            )
            if item.id == outbox_id else item
            for item in self.outbox_items
        ]


def test_delete_attachment_survives_transient_storage_failure() -> None:
    repository = FakeSupportRepository()
    storage = DummyStorage(should_fail=True)
    service = SupportService(
        repository=repository,  # type: ignore[arg-type]
        signer=DummySigner(),
        attachment_storage=storage,
        clock=lambda: NOW,
    )

    # Should not raise even though storage.delete throws
    asyncio.run(
        service.delete_attachment(
            organization_id=ORG_ID,
            ticket_id=TICKET_ID,
            attachment_id=ATTACHMENT_ID,
            actor_id=USER_ID,
            owner_only=False,
            trace=RequestTrace(None, None),
        )
    )

    assert repository.attachment_deleted is True
    assert len(repository.outbox_items) == 1
    assert repository.outbox_items[0].status == "PENDING"
    assert repository.outbox_items[0].storage_path == "private/test.png"


def test_outbox_processor_successfully_sweeps_and_completes_deletions() -> None:
    repository = FakeSupportRepository()
    storage = DummyStorage(should_fail=False)
    service = SupportService(
        repository=repository,  # type: ignore[arg-type]
        signer=DummySigner(),
        attachment_storage=storage,
        clock=lambda: NOW,
    )

    # Populate pending outbox
    repository.outbox_items.append(
        AttachmentDeletionOutboxItem(
            id=OUTBOX_ID,
            organization_id=ORG_ID,
            storage_path="private/queued_file.png",
            status="PENDING",
            attempts=0,
            max_attempts=5,
            created_at=NOW,
        )
    )

    processed = asyncio.run(
        service.process_pending_attachment_deletions(ORG_ID, batch_size=10)
    )

    assert processed == 1
    assert "private/queued_file.png" in storage.deleted_paths
    assert OUTBOX_ID in repository.completed_ids
    assert repository.outbox_items[0].status == "COMPLETED"


def test_outbox_processor_records_failures_and_increments_attempts() -> None:
    repository = FakeSupportRepository()
    storage = DummyStorage(should_fail=True)
    service = SupportService(
        repository=repository,  # type: ignore[arg-type]
        signer=DummySigner(),
        attachment_storage=storage,
        clock=lambda: NOW,
    )

    repository.outbox_items.append(
        AttachmentDeletionOutboxItem(
            id=OUTBOX_ID,
            organization_id=ORG_ID,
            storage_path="private/bad_file.png",
            status="PENDING",
            attempts=4,
            max_attempts=5,
            created_at=NOW,
        )
    )

    processed = asyncio.run(
        service.process_pending_attachment_deletions(ORG_ID, batch_size=10)
    )

    assert processed == 0
    assert len(repository.failed_ids) == 1
    assert repository.outbox_items[0].status == "FAILED"
    assert repository.outbox_items[0].attempts == 5
