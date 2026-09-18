import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.support.attachments import LocalAttachmentStorage
from backend.app.support.crypto import Ed25519ActionSigner
from backend.app.support.schemas import (
    MAX_ATTACHMENT_BYTES,
    AttachmentMetadata,
    validate_attachment,
)
from backend.app.support.service import (
    RequestTrace,
    SupportService,
    SupportUnavailable,
)


def test_local_attachment_storage_uses_private_generated_path(tmp_path: Path) -> None:
    storage = LocalAttachmentStorage(tmp_path / "private")
    metadata = validate_attachment(
        original_name="screen.png",
        content=b"\x89PNG\r\n\x1a\ncontent",
    )

    relative = asyncio.run(
        storage.store(
            organization_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            ticket_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            metadata=metadata,
            content=b"\x89PNG\r\n\x1a\ncontent",
        )
    )

    assert not Path(relative).is_absolute()
    assert metadata.original_name not in relative
    assert asyncio.run(storage.read(relative)) == b"\x89PNG\r\n\x1a\ncontent"
    asyncio.run(storage.delete(relative))
    assert not (tmp_path / "private" / relative).exists()


def test_local_attachment_storage_rejects_path_escape(tmp_path: Path) -> None:
    storage = LocalAttachmentStorage(tmp_path / "private")

    with pytest.raises(ValueError, match="Ruta de adjunto inválida"):
        asyncio.run(storage.read("../outside.pdf"))


def test_local_attachment_storage_requires_absolute_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="La raíz de adjuntos debe ser absoluta"):
        LocalAttachmentStorage(Path("relative/path"))


def test_validate_attachment_rejects_disallowed_magic_bytes() -> None:
    with pytest.raises(ValueError, match="Tipo de archivo no permitido"):
        validate_attachment(
            original_name="malicious.exe",
            content=b"MZ\x90\x00\x03\x00\x00\x00",
        )


def test_validate_attachment_rejects_oversized_content() -> None:
    with pytest.raises(ValueError, match="El archivo excede 10 MB"):
        validate_attachment(
            original_name="big.png",
            content=b"\x89PNG\r\n\x1a\n" + b"0" * (MAX_ATTACHMENT_BYTES + 1),
        )


def test_support_service_rolls_back_storage_on_repository_failure(tmp_path: Path) -> None:
    storage = LocalAttachmentStorage(tmp_path / "private")
    repo = AsyncMock()
    repo.create_attachment.side_effect = RuntimeError("Database error")

    signer = MagicMock(spec=Ed25519ActionSigner)
    service = SupportService(
        repository=repo,
        signer=signer,
        attachment_storage=storage,
        clock=lambda: datetime.now(UTC),
    )

    org_id = uuid4()
    ticket_id = uuid4()
    actor_id = uuid4()

    with pytest.raises(RuntimeError, match="Database error"):
        asyncio.run(
            service.upload_attachment(
                organization_id=org_id,
                ticket_id=ticket_id,
                actor_id=actor_id,
                original_name="report.pdf",
                content=b"%PDF-1.4 test pdf content",
                owner_only=False,
                trace=RequestTrace(ip_address="127.0.0.1", user_agent="test"),
            )
        )

    # Verify that storage was rolled back and no file was left on disk
    stored_files = list((tmp_path / "private").rglob("*.pdf")) + list((tmp_path / "private").rglob("*.bin"))
    assert len(stored_files) == 0
