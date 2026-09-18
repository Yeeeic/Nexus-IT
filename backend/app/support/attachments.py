"""Private local attachment storage with path confinement."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from backend.app.support.schemas import AttachmentMetadata, MAX_ATTACHMENT_BYTES


class LocalAttachmentStorage:
    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("La raíz de adjuntos debe ser absoluta")
        self._root = root.resolve()
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            try:
                os.chmod(self._root, 0o700)
            except OSError:
                pass

    def _confined(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute():
            raise ValueError("Ruta de adjunto inválida")
        candidate = (self._root / relative).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            raise ValueError("Ruta de adjunto inválida") from None
        return candidate

    async def store(
        self,
        *,
        organization_id: str,
        ticket_id: str,
        metadata: AttachmentMetadata,
        content: bytes,
    ) -> str:
        relative = str(
            Path(organization_id) / ticket_id / metadata.stored_filename
        )
        destination = self._confined(relative)

        def write() -> None:
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                os.chmod(destination.parent, 0o700)
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                destination.unlink(missing_ok=True)
                raise

        await asyncio.to_thread(write)
        return relative

    async def read(self, relative_path: str) -> bytes:
        source = self._confined(relative_path)

        def load() -> bytes:
            if not source.is_file():
                raise FileNotFoundError
            with source.open("rb") as handle:
                content = handle.read(MAX_ATTACHMENT_BYTES + 1)
            if len(content) > MAX_ATTACHMENT_BYTES:
                raise ValueError("El archivo excede 10 MB")
            return content

        return await asyncio.to_thread(load)

    async def delete(self, relative_path: str) -> None:
        target = self._confined(relative_path)
        await asyncio.to_thread(target.unlink, missing_ok=True)
