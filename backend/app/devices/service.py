"""Device, inventory, and machine-token contracts."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import re
import secrets
from typing import Protocol
from uuid import UUID, uuid4


def hash_device_secret(secret: str, pepper: bytes) -> bytes:
    if len(pepper) < 32:
        raise ValueError("device token pepper must contain at least 32 bytes")
    return hmac.new(pepper, secret.encode("ascii"), hashlib.sha256).digest()


def parse_device_token(value: str) -> tuple[UUID, str]:
    try:
        token_id_value, secret = value.split(".", maxsplit=1)
        token_id = UUID(token_id_value)
    except (AttributeError, ValueError):
        raise ValueError("invalid device token") from None
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", secret) is None:
        raise ValueError("invalid device token")
    try:
        secret.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("invalid device token") from None
    return token_id, secret


@dataclass(frozen=True, slots=True)
class DeviceToken:
    token_id: UUID
    value: str
    secret_hash: bytes

    @classmethod
    def generate(cls, pepper: bytes) -> "DeviceToken":
        token_id = uuid4()
        secret = secrets.token_urlsafe(32)
        return cls(
            token_id=token_id,
            value=f"{token_id}.{secret}",
            secret_hash=hash_device_secret(secret, pepper),
        )

    def __repr__(self) -> str:
        return (
            f"DeviceToken(token_id={self.token_id!r}, "
            "value=Secret('**********'))"
        )


@dataclass(frozen=True, slots=True)
class DeviceTokenRecord:
    token_id: UUID
    organization_id: UUID
    device_id: UUID
    secret_hash: bytes
    expires_at: datetime | None
    is_revoked: bool


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    organization_id: UUID
    device_id: UUID
    token_id: UUID


class AgentTokenRejected(Exception):
    def __init__(self) -> None:
        super().__init__("Autenticación de agente requerida")


class AgentTokenUnavailable(Exception):
    def __init__(self) -> None:
        super().__init__("Servicio temporalmente no disponible")


class AgentTokenRepository(Protocol):
    async def find_token(self, token_id: UUID) -> DeviceTokenRecord | None: ...

    async def activate_identity(
        self,
        record: DeviceTokenRecord,
        *,
        used_at: datetime,
    ) -> bool: ...


AgentRepositoryFactory = Callable[
    [], AbstractAsyncContextManager[AgentTokenRepository]
]


class AgentTokenApplication:
    def __init__(
        self,
        repository_factory: AgentRepositoryFactory,
        *,
        pepper: bytes,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(pepper) < 32:
            raise ValueError("device token pepper must contain at least 32 bytes")
        self._repository_factory = repository_factory
        self._pepper = pepper
        self._clock = clock

    async def authenticate(self, token: str) -> AgentIdentity:
        try:
            token_id, secret = parse_device_token(token)
            parsed = True
        except ValueError:
            token_id, secret = UUID(int=0), "invalid"
            parsed = False
        presented_hash = hash_device_secret(secret, self._pepper)
        now = self._clock()

        try:
            async with self._repository_factory() as repository:
                record = await repository.find_token(token_id)
                stored_hash = record.secret_hash if record else bytes(32)
                matches = hmac.compare_digest(stored_hash, presented_hash)
                valid = bool(
                    parsed
                    and record is not None
                    and not record.is_revoked
                    and (
                        record.expires_at is None
                        or record.expires_at > now
                    )
                    and matches
                )
                if not valid or record is None:
                    raise AgentTokenRejected
                active = await repository.activate_identity(
                    record,
                    used_at=now,
                )
                if not active:
                    raise AgentTokenRejected
                return AgentIdentity(
                    organization_id=record.organization_id,
                    device_id=record.device_id,
                    token_id=record.token_id,
                )
        except AgentTokenRejected:
            raise
        except Exception:
            raise AgentTokenUnavailable from None


@dataclass(frozen=True, slots=True)
class AuditContext:
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class DeviceEnrollment:
    hostname: str
    display_name: str | None
    token_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class DeviceUpdate:
    display_name: str | None


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    organization_id: UUID
    id: UUID
    hostname: str
    display_name: str | None
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DeviceEnrollmentResult:
    device: DeviceRecord
    token_id: UUID
    token: str
    token_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class DeviceTokenResult:
    token_id: UUID
    token: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class InventorySnapshotWrite:
    hardware: dict[str, object]
    software_packages: tuple[dict[str, object], ...]
    patches: tuple[dict[str, object], ...]
    services: tuple[dict[str, object], ...]
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    organization_id: UUID
    device_id: UUID
    hardware: dict[str, object]
    software_packages: tuple[dict[str, object], ...]
    patches: tuple[dict[str, object], ...]
    services: tuple[dict[str, object], ...]
    collected_at: datetime
    updated_at: datetime


class DeviceNotFound(Exception):
    pass


class DeviceConflict(Exception):
    pass


class DeviceService(Protocol):
    async def enroll(
        self,
        organization_id: UUID,
        actor_id: UUID,
        command: DeviceEnrollment,
        audit: AuditContext,
    ) -> DeviceEnrollmentResult: ...

    async def list_devices(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        assigned_only: bool,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[DeviceRecord, ...], UUID | None]: ...

    async def get_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        *,
        actor_id: UUID,
        assigned_only: bool,
    ) -> DeviceRecord: ...

    async def update_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        command: DeviceUpdate,
        audit: AuditContext,
    ) -> DeviceRecord: ...

    async def delete_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        audit: AuditContext,
    ) -> None: ...

    async def rotate_token(
        self,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        *,
        expires_at: datetime | None,
        audit: AuditContext,
    ) -> DeviceTokenResult: ...

    async def revoke_token(
        self,
        organization_id: UUID,
        device_id: UUID,
        token_id: UUID,
        actor_id: UUID,
        audit: AuditContext,
    ) -> None: ...

    async def get_inventory(
        self,
        organization_id: UUID,
        device_id: UUID,
        *,
        actor_id: UUID,
        assigned_only: bool,
    ) -> InventorySnapshot: ...

    async def assign_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        user_id: UUID,
        actor_id: UUID,
        audit: AuditContext,
    ) -> None: ...

    async def unassign_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        user_id: UUID,
        actor_id: UUID,
        audit: AuditContext,
    ) -> None: ...

    async def write_inventory(
        self,
        identity: AgentIdentity,
        snapshot: InventorySnapshotWrite,
    ) -> InventorySnapshot: ...
