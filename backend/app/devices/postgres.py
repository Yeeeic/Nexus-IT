"""Async PostgreSQL persistence for tenant devices and machine tokens."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import json
from types import TracebackType
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.app.devices.service import (
    AgentIdentity,
    AuditContext,
    DeviceConflict,
    DeviceEnrollment,
    DeviceEnrollmentResult,
    DeviceNotFound,
    DeviceRecord,
    DeviceToken,
    DeviceTokenRecord,
    DeviceTokenResult,
    DeviceUpdate,
    InventorySnapshot,
    InventorySnapshotWrite,
)


class AsyncTransaction(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class AsyncConnection(Protocol):
    async def begin(self) -> AsyncTransaction: ...

    async def execute(
        self,
        statement: object,
        parameters: dict[str, object] | None = None,
    ) -> Any: ...

    async def close(self) -> None: ...


class AsyncBeginContext(Protocol):
    async def __aenter__(self) -> AsyncConnection: ...

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class AsyncEngine(Protocol):
    async def connect(self) -> AsyncConnection: ...

    def begin(self) -> AsyncBeginContext: ...


class PostgresAgentTokenRepository:
    """Resolve public token ID globally, then enter verified tenant RLS."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._connection: AsyncConnection | None = None
        self._transaction: AsyncTransaction | None = None

    async def __aenter__(self) -> "PostgresAgentTokenRepository":
        if self._connection is not None:
            raise RuntimeError("agent token repository is already active")
        connection = await self._engine.connect()
        transaction = await connection.begin()
        self._connection = connection
        self._transaction = transaction
        try:
            await connection.execute(text("SET LOCAL ROLE nexus_auth_user"))
        except BaseException:
            await transaction.rollback()
            await connection.close()
            self._connection = None
            self._transaction = None
            raise
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        connection = self._required_connection()
        transaction = cast(AsyncTransaction, self._transaction)
        try:
            if exception_type is None:
                await transaction.commit()
            else:
                await transaction.rollback()
        finally:
            await connection.close()
            self._connection = None
            self._transaction = None

    def _required_connection(self) -> AsyncConnection:
        if self._connection is None:
            raise RuntimeError("agent token repository is outside a transaction")
        return self._connection

    async def find_token(self, token_id: UUID) -> DeviceTokenRecord | None:
        result = await self._required_connection().execute(
            text(
                """
                SELECT
                    id AS token_id,
                    organization_id,
                    device_id,
                    token_hash,
                    expires_at,
                    is_revoked
                FROM public.device_tokens
                WHERE id = :token_id
                LIMIT 1
                """
            ),
            {"token_id": token_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return DeviceTokenRecord(
            token_id=row["token_id"],
            organization_id=row["organization_id"],
            device_id=row["device_id"],
            secret_hash=row["token_hash"],
            expires_at=row["expires_at"],
            is_revoked=row["is_revoked"],
        )

    async def activate_identity(
        self,
        record: DeviceTokenRecord,
        *,
        used_at: datetime,
    ) -> bool:
        connection = self._required_connection()
        await connection.execute(text("SET LOCAL ROLE nexus_app_user"))
        await connection.execute(
            text(
                "SELECT set_config("
                "'app.current_organization_id', :organization_id, true)"
            ),
            {"organization_id": str(record.organization_id)},
        )
        result = await connection.execute(
            text(
                """
                SELECT true AS active
                FROM public.device_tokens AS token
                JOIN public.devices AS device
                  ON device.organization_id = token.organization_id
                 AND device.id = token.device_id
                JOIN public.organizations AS organization
                  ON organization.id = token.organization_id
                WHERE token.organization_id = :organization_id
                  AND token.id = :token_id
                  AND token.device_id = :device_id
                  AND NOT token.is_revoked
                  AND (token.expires_at IS NULL OR token.expires_at > :used_at)
                  AND device.is_active
                  AND organization.is_active
                FOR SHARE OF token
                """
            ),
            {
                "organization_id": record.organization_id,
                "device_id": record.device_id,
                "token_id": record.token_id,
                "used_at": used_at,
            },
        )
        if result.mappings().one_or_none() is None:
            return False
        update = await connection.execute(
            text(
                """
                UPDATE public.device_tokens
                SET last_used_at = :used_at
                WHERE organization_id = :organization_id
                  AND id = :token_id
                  AND device_id = :device_id
                  AND NOT is_revoked
                """
            ),
            {
                "organization_id": record.organization_id,
                "device_id": record.device_id,
                "token_id": record.token_id,
                "used_at": used_at,
            },
        )
        return update.rowcount == 1


class PostgresDeviceService:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        pepper: bytes,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if len(pepper) < 32:
            raise ValueError("device token pepper must contain at least 32 bytes")
        self._engine = engine
        self._pepper = pepper
        self._clock = clock
        self._id_factory = id_factory

    @asynccontextmanager
    async def _tenant_connection(
        self,
        organization_id: UUID,
    ) -> AsyncIterator[AsyncConnection]:
        async with self._engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE nexus_app_user"))
            await connection.execute(
                text(
                    "SELECT set_config("
                    "'app.current_organization_id', :organization_id, true)"
                ),
                {"organization_id": str(organization_id)},
            )
            yield connection

    def _validate_expiry(self, expires_at: datetime | None) -> None:
        if expires_at is not None and (
            expires_at.utcoffset() is None or expires_at <= self._clock()
        ):
            raise DeviceConflict("token expiry must be in the future")

    @staticmethod
    def _device(row: Any) -> DeviceRecord:
        return DeviceRecord(
            organization_id=row["organization_id"],
            id=row["id"],
            hostname=row["hostname"],
            display_name=row["display_name"],
            is_active=row["is_active"],
            last_seen_at=row["last_seen_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _inventory(row: Any) -> InventorySnapshot:
        return InventorySnapshot(
            organization_id=row["organization_id"],
            device_id=row["device_id"],
            hardware=row["hardware"],
            software_packages=tuple(row["software_packages"]),
            patches=tuple(row["patches"]),
            services=tuple(row["services"]),
            collected_at=row["collected_at"],
            updated_at=row["updated_at"],
        )

    async def _append_audit(
        self,
        connection: AsyncConnection,
        *,
        organization_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        audit: AuditContext,
    ) -> None:
        await connection.execute(
            text(
                """
                INSERT INTO public.audit_logs (
                    id, organization_id, actor_id, actor_type, ip_address,
                    user_agent, action, resource_type, resource_id, status,
                    details
                ) VALUES (
                    :id, :organization_id, :actor_id, 'USER', :ip_address,
                    :user_agent, :action, 'DEVICE', :resource_id, 'SUCCESS',
                    CAST(:details AS jsonb)
                )
                """
            ),
            {
                "id": self._id_factory(),
                "organization_id": organization_id,
                "actor_id": actor_id,
                "ip_address": audit.ip_address,
                "user_agent": (audit.user_agent or "").strip()[:255] or None,
                "action": action,
                "resource_id": resource_id,
                "details": "{}",
            },
        )

    async def enroll(
        self,
        organization_id: UUID,
        actor_id: UUID,
        command: DeviceEnrollment,
        audit: AuditContext,
    ) -> DeviceEnrollmentResult:
        self._validate_expiry(command.token_expires_at)
        device_id = self._id_factory()
        token = DeviceToken.generate(self._pepper)
        now = self._clock()
        try:
            async with self._tenant_connection(organization_id) as connection:
                result = await connection.execute(
                    text(
                        """
                        INSERT INTO public.devices (
                            organization_id, id, hostname, display_name,
                            created_at, updated_at
                        ) VALUES (
                            :organization_id, :device_id, :hostname,
                            :display_name, :now, :now
                        )
                        RETURNING organization_id, id, hostname, display_name,
                                  is_active, last_seen_at, created_at, updated_at
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "device_id": device_id,
                        "hostname": command.hostname.lower(),
                        "display_name": command.display_name,
                        "now": now,
                    },
                )
                row = result.mappings().one_or_none()
                if row is None:
                    raise RuntimeError("device enrollment returned no row")
                await connection.execute(
                    text(
                        """
                        INSERT INTO public.device_tokens (
                            organization_id, id, device_id, token_hash,
                            expires_at, created_at
                        ) VALUES (
                            :organization_id, :token_id, :device_id,
                            :token_hash, :expires_at, :created_at
                        )
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "token_id": token.token_id,
                        "device_id": device_id,
                        "token_hash": token.secret_hash,
                        "expires_at": command.token_expires_at,
                        "created_at": now,
                    },
                )
                await self._append_audit(
                    connection,
                    organization_id=organization_id,
                    actor_id=actor_id,
                    action="DEVICE.ENROLLED",
                    resource_id=device_id,
                    audit=audit,
                )
        except IntegrityError:
            raise DeviceConflict("device already exists") from None
        return DeviceEnrollmentResult(
            device=self._device(row),
            token_id=token.token_id,
            token=token.value,
            token_expires_at=command.token_expires_at,
        )

    async def list_devices(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        assigned_only: bool,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[DeviceRecord, ...], UUID | None]:
        async with self._tenant_connection(organization_id) as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT organization_id, id, hostname, display_name,
                           is_active, last_seen_at, created_at, updated_at
                    FROM public.devices
                    WHERE organization_id = :organization_id
                      AND is_active
                      AND (CAST(:after_id AS uuid) IS NULL OR id > CAST(:after_id AS uuid))
                      AND (
                          NOT :assigned_only OR EXISTS (
                              SELECT 1
                              FROM public.device_assignments AS assignment
                              WHERE assignment.organization_id = devices.organization_id
                                AND assignment.device_id = devices.id
                                AND assignment.user_id = :actor_id
                          )
                      )
                    ORDER BY id
                    LIMIT :fetch_limit
                    """
                ),
                {
                    "organization_id": organization_id,
                    "actor_id": actor_id,
                    "assigned_only": assigned_only,
                    "after_id": after_id,
                    "fetch_limit": limit + 1,
                },
            )
            rows = result.mappings().all()
        items = tuple(self._device(row) for row in rows[:limit])
        next_cursor = items[-1].id if len(rows) > limit and items else None
        return items, next_cursor

    async def get_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        *,
        actor_id: UUID,
        assigned_only: bool,
    ) -> DeviceRecord:
        async with self._tenant_connection(organization_id) as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT organization_id, id, hostname, display_name,
                           is_active, last_seen_at, created_at, updated_at
                    FROM public.devices
                    WHERE organization_id = :organization_id
                      AND id = :device_id
                      AND is_active
                      AND (
                          NOT :assigned_only OR EXISTS (
                              SELECT 1
                              FROM public.device_assignments AS assignment
                              WHERE assignment.organization_id = devices.organization_id
                                AND assignment.device_id = devices.id
                                AND assignment.user_id = :actor_id
                          )
                      )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "actor_id": actor_id,
                    "assigned_only": assigned_only,
                },
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise DeviceNotFound
        return self._device(row)

    async def update_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        command: DeviceUpdate,
        audit: AuditContext,
    ) -> DeviceRecord:
        now = self._clock()
        async with self._tenant_connection(organization_id) as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE public.devices
                    SET display_name = :display_name,
                        updated_at = :updated_at
                    WHERE organization_id = :organization_id
                      AND id = :device_id
                      AND is_active
                    RETURNING organization_id, id, hostname, display_name,
                              is_active, last_seen_at, created_at, updated_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "display_name": command.display_name,
                    "updated_at": now,
                },
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise DeviceNotFound
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                action="DEVICE.UPDATED",
                resource_id=device_id,
                audit=audit,
            )
        return self._device(row)

    async def delete_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        audit: AuditContext,
    ) -> None:
        now = self._clock()
        async with self._tenant_connection(organization_id) as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE public.devices
                    SET is_active = false, updated_at = :now
                    WHERE organization_id = :organization_id
                      AND id = :device_id
                      AND is_active
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "now": now,
                },
            )
            if result.rowcount != 1:
                raise DeviceNotFound
            await connection.execute(
                text(
                    """
                    UPDATE public.device_tokens
                    SET is_revoked = true, revoked_at = :now
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND NOT is_revoked
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "now": now,
                },
            )
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                action="DEVICE.DELETED",
                resource_id=device_id,
                audit=audit,
            )

    async def rotate_token(
        self,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        *,
        expires_at: datetime | None,
        overlap_seconds: int = 300,
        audit: AuditContext,
    ) -> DeviceTokenResult:
        self._validate_expiry(expires_at)
        if not 0 <= overlap_seconds <= 3600:
            raise DeviceConflict("invalid token overlap")
        now = self._clock()
        overlap_until = now + timedelta(seconds=overlap_seconds)
        token = DeviceToken.generate(self._pepper)
        async with self._tenant_connection(organization_id) as connection:
            device = await connection.execute(
                text(
                    """
                    SELECT true AS active
                    FROM public.devices
                    WHERE organization_id = :organization_id
                      AND id = :device_id
                      AND is_active
                    FOR SHARE
                    """
                ),
                {"organization_id": organization_id, "device_id": device_id},
            )
            if device.mappings().one_or_none() is None:
                raise DeviceNotFound
            await connection.execute(
                text(
                    """
                    UPDATE public.device_tokens
                    SET expires_at = LEAST(
                            COALESCE(expires_at, :overlap_until),
                            :overlap_until
                        )
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND NOT is_revoked
                      AND (expires_at IS NULL OR expires_at > :overlap_until)
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "overlap_until": overlap_until,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO public.device_tokens (
                        organization_id, id, device_id, token_hash,
                        expires_at, created_at
                    ) VALUES (
                        :organization_id, :token_id, :device_id,
                        :token_hash, :expires_at, :created_at
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "token_id": token.token_id,
                    "device_id": device_id,
                    "token_hash": token.secret_hash,
                    "expires_at": expires_at,
                    "created_at": now,
                },
            )
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                action="DEVICE.TOKEN_ROTATED",
                resource_id=device_id,
                audit=audit,
            )
        return DeviceTokenResult(token.token_id, token.value, expires_at)

    async def revoke_token(
        self,
        organization_id: UUID,
        device_id: UUID,
        token_id: UUID,
        actor_id: UUID,
        audit: AuditContext,
    ) -> None:
        now = self._clock()
        async with self._tenant_connection(organization_id) as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE public.device_tokens
                    SET is_revoked = true, revoked_at = :revoked_at
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :token_id
                      AND NOT is_revoked
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "token_id": token_id,
                    "revoked_at": now,
                },
            )
            if result.rowcount != 1:
                raise DeviceNotFound
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                action="DEVICE.TOKEN_REVOKED",
                resource_id=device_id,
                audit=audit,
            )

    async def get_inventory(
        self,
        organization_id: UUID,
        device_id: UUID,
        *,
        actor_id: UUID,
        assigned_only: bool,
    ) -> InventorySnapshot:
        async with self._tenant_connection(organization_id) as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT organization_id, device_id, hardware,
                           software_packages, patches, services,
                           collected_at, updated_at
                    FROM public.device_inventory
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND (
                          NOT :assigned_only OR EXISTS (
                              SELECT 1
                              FROM public.device_assignments AS assignment
                              WHERE assignment.organization_id = device_inventory.organization_id
                                AND assignment.device_id = device_inventory.device_id
                                AND assignment.user_id = :actor_id
                          )
                      )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "actor_id": actor_id,
                    "assigned_only": assigned_only,
                },
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise DeviceNotFound
        return self._inventory(row)

    async def assign_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        user_id: UUID,
        actor_id: UUID,
        audit: AuditContext,
    ) -> None:
        async with self._tenant_connection(organization_id) as connection:
            result = await connection.execute(
                text(
                    """
                    INSERT INTO public.device_assignments (
                        organization_id, device_id, user_id, assigned_by
                    )
                    SELECT :organization_id, device.id, membership.user_id, :actor_id
                    FROM public.devices AS device
                    JOIN public.organization_memberships AS membership
                      ON membership.organization_id = device.organization_id
                     AND membership.user_id = :user_id
                     AND membership.is_active
                    WHERE device.organization_id = :organization_id
                      AND device.id = :device_id
                      AND device.is_active
                    ON CONFLICT (organization_id, device_id, user_id) DO NOTHING
                    RETURNING device_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "user_id": user_id,
                    "actor_id": actor_id,
                },
            )
            if result.mappings().one_or_none() is None:
                existing = await connection.execute(
                    text(
                        """
                        SELECT true AS assigned
                        FROM public.device_assignments
                        WHERE organization_id = :organization_id
                          AND device_id = :device_id
                          AND user_id = :user_id
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "device_id": device_id,
                        "user_id": user_id,
                    },
                )
                if existing.mappings().one_or_none() is None:
                    raise DeviceNotFound
                return
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                action="DEVICE.ASSIGNED",
                resource_id=device_id,
                audit=audit,
            )

    async def unassign_device(
        self,
        organization_id: UUID,
        device_id: UUID,
        user_id: UUID,
        actor_id: UUID,
        audit: AuditContext,
    ) -> None:
        async with self._tenant_connection(organization_id) as connection:
            result = await connection.execute(
                text(
                    """
                    DELETE FROM public.device_assignments
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND user_id = :user_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "user_id": user_id,
                },
            )
            if result.rowcount != 1:
                raise DeviceNotFound
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                action="DEVICE.UNASSIGNED",
                resource_id=device_id,
                audit=audit,
            )

    async def write_inventory(
        self,
        identity: AgentIdentity,
        snapshot: InventorySnapshotWrite,
    ) -> InventorySnapshot:
        now = self._clock()
        if (
            snapshot.collected_at.utcoffset() is None
            or snapshot.collected_at > now + timedelta(minutes=5)
            or snapshot.collected_at < now - timedelta(days=90)
        ):
            raise DeviceConflict("inventory collection time is outside allowed range")
        async with self._tenant_connection(identity.organization_id) as connection:
            current_identity = await connection.execute(
                text(
                    """
                    SELECT true AS active
                    FROM public.device_tokens AS token
                    JOIN public.devices AS device
                      ON device.organization_id = token.organization_id
                     AND device.id = token.device_id
                    WHERE token.organization_id = :organization_id
                      AND token.device_id = :device_id
                      AND token.id = :token_id
                      AND NOT token.is_revoked
                      AND (token.expires_at IS NULL OR token.expires_at > :now)
                      AND device.is_active
                    FOR SHARE OF token
                    """
                ),
                {
                    "organization_id": identity.organization_id,
                    "device_id": identity.device_id,
                    "token_id": identity.token_id,
                    "now": now,
                },
            )
            if current_identity.mappings().one_or_none() is None:
                raise DeviceNotFound
            result = await connection.execute(
                text(
                    """
                    INSERT INTO public.device_inventory (
                        organization_id, device_id, hardware,
                        software_packages, patches, services,
                        collected_at, updated_at
                    ) VALUES (
                        :organization_id, :device_id, CAST(:hardware AS jsonb),
                        CAST(:software_packages AS jsonb), CAST(:patches AS jsonb),
                        CAST(:services AS jsonb), :collected_at, :updated_at
                    )
                    ON CONFLICT (organization_id, device_id) DO UPDATE
                    SET hardware = EXCLUDED.hardware,
                        software_packages = EXCLUDED.software_packages,
                        patches = EXCLUDED.patches,
                        services = EXCLUDED.services,
                        collected_at = EXCLUDED.collected_at,
                        updated_at = EXCLUDED.updated_at
                    WHERE EXCLUDED.collected_at >= public.device_inventory.collected_at
                    RETURNING organization_id, device_id, hardware,
                              software_packages, patches, services,
                              collected_at, updated_at
                    """
                ),
                {
                    "organization_id": identity.organization_id,
                    "device_id": identity.device_id,
                    "hardware": json.dumps(snapshot.hardware, separators=(",", ":")),
                    "software_packages": json.dumps(
                        snapshot.software_packages, separators=(",", ":")
                    ),
                    "patches": json.dumps(snapshot.patches, separators=(",", ":")),
                    "services": json.dumps(snapshot.services, separators=(",", ":")),
                    "collected_at": snapshot.collected_at,
                    "updated_at": now,
                },
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise DeviceConflict("inventory snapshot is older than current state")
            await connection.execute(
                text(
                    """
                    UPDATE public.devices
                    SET last_seen_at = :last_seen_at,
                        updated_at = GREATEST(updated_at, :last_seen_at)
                    WHERE organization_id = :organization_id
                      AND id = :device_id
                      AND is_active
                    """
                ),
                {
                    "organization_id": identity.organization_id,
                    "device_id": identity.device_id,
                    "last_seen_at": now,
                },
            )
        return self._inventory(row)
