"""Async PostgreSQL transaction boundary for login persistence."""

import json
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import text

from backend.app.audit import AuditEvent
from backend.app.auth.login import ActiveMembership, SessionCreation
from backend.app.auth.password_reset import PasswordResetRecord
from backend.app.auth.session import SessionRecord
from backend.app.auth.service import CredentialRecord


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


class AsyncEngine(Protocol):
    async def connect(self) -> AsyncConnection: ...


class PostgresLoginRepository:
    """Single-use login unit of work using the restricted authentication role."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._connection: AsyncConnection | None = None
        self._transaction: AsyncTransaction | None = None
        self._verified_user_id: UUID | None = None
        self._loaded_session: tuple[UUID, UUID] | None = None
        self._loaded_password_reset: tuple[UUID, UUID] | None = None
        self._verified_reset_user_id: UUID | None = None

    async def __aenter__(self) -> "PostgresLoginRepository":
        if self._connection is not None:
            raise RuntimeError("login repository is already active")
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
            self._verified_user_id = None
            self._loaded_session = None
            self._loaded_password_reset = None
            self._verified_reset_user_id = None

    def _required_connection(self) -> AsyncConnection:
        if self._connection is None:
            raise RuntimeError("login repository is outside a transaction")
        return self._connection

    async def find_by_email(
        self,
        normalized_email: str,
    ) -> CredentialRecord | None:
        result = await self._required_connection().execute(
            text(
                """
                SELECT
                    id AS user_id,
                    password_hash,
                    is_active,
                    locked_until
                FROM public.users
                WHERE email = :email
                LIMIT 1
                """
            ),
            {"email": normalized_email},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return CredentialRecord(
            user_id=row["user_id"],
            password_hash=row["password_hash"],
            is_active=row["is_active"],
            locked_until=row["locked_until"],
        )

    async def get_user_profile(
        self,
        user_id: UUID,
    ) -> tuple[str, str]:
        connection = self._required_connection()
        await connection.execute(
            text("SELECT set_config('app.current_user_id', :user_id, true)"),
            {"user_id": str(user_id)},
        )
        result = await connection.execute(
            text(
                """
                SELECT email, full_name
                FROM public.users
                WHERE id = :user_id AND is_active = true
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise RuntimeError("user not found or inactive")
        return row["email"], row["full_name"]

    async def list_active_for_user(
        self,
        user_id: UUID,
    ) -> tuple[ActiveMembership, ...]:
        connection = self._required_connection()
        await connection.execute(
            text(
                "SELECT set_config('app.current_user_id', :user_id, true)"
            ),
            {"user_id": str(user_id)},
        )
        result = await connection.execute(
            text(
                """
                SELECT
                    organization.id AS organization_id,
                    organization.name AS organization_name
                FROM public.organization_memberships AS membership
                JOIN public.organizations AS organization
                  ON organization.id = membership.organization_id
                WHERE membership.user_id = :user_id
                  AND membership.is_active
                  AND organization.is_active
                ORDER BY organization.name, organization.id
                """
            ),
            {"user_id": user_id},
        )
        self._verified_user_id = user_id
        return tuple(
            ActiveMembership(
                organization_id=row["organization_id"],
                organization_name=row["organization_name"],
            )
            for row in result.mappings().all()
        )

    async def replace_for_login(
        self,
        creation: SessionCreation,
        *,
        previous_token_hash: bytes | None,
    ) -> None:
        if creation.user_id != self._verified_user_id:
            raise RuntimeError("verified user context is required")
        connection = self._required_connection()

        if previous_token_hash is not None:
            await connection.execute(
                text(
                    """
                    SELECT set_config(
                        'app.current_session_token_hash',
                        :previous_token_hash,
                        true
                    )
                    """
                ),
                {"previous_token_hash": previous_token_hash.hex()},
            )
            await connection.execute(
                text(
                    """
                    UPDATE public.user_sessions
                    SET is_revoked = true
                    WHERE user_id = :user_id
                      AND NOT is_revoked
                    """
                ),
                {"user_id": creation.user_id},
            )

        await connection.execute(
            text(
                """
                INSERT INTO public.user_sessions (
                    id,
                    organization_id,
                    user_id,
                    session_token_hash,
                    csrf_token_hash,
                    expires_at,
                    last_seen_at,
                    created_at,
                    user_agent,
                    ip_address
                ) VALUES (
                    :session_id,
                    :organization_id,
                    :user_id,
                    :session_token_hash,
                    :csrf_token_hash,
                    :expires_at,
                    :last_seen_at,
                    :created_at,
                    :user_agent,
                    :ip_address
                )
                """
            ),
            {
                "session_id": creation.session_id,
                "organization_id": creation.organization_id,
                "user_id": creation.user_id,
                "session_token_hash": creation.session_token_hash,
                "csrf_token_hash": creation.csrf_token_hash,
                "expires_at": creation.expires_at,
                "last_seen_at": creation.last_seen_at,
                "created_at": creation.last_seen_at,
                "user_agent": creation.user_agent,
                "ip_address": creation.ip_address,
            },
        )

    async def append_audit(self, event: AuditEvent) -> None:
        await self._required_connection().execute(
            text(
                """
                INSERT INTO public.audit_logs (
                    id, organization_id, actor_id, actor_type, ip_address,
                    user_agent, action, resource_type, resource_id, status,
                    details
                ) VALUES (
                    :id, :organization_id, :actor_id, :actor_type, :ip_address,
                    :user_agent, :action, :resource_type, :resource_id, :status,
                    CAST(:details AS jsonb)
                )
                """
            ),
            {
                "id": event.id,
                "organization_id": event.organization_id,
                "actor_id": event.actor_id,
                "actor_type": event.actor_type,
                "ip_address": event.ip_address,
                "user_agent": event.user_agent,
                "action": event.action,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "status": event.status,
                "details": json.dumps(
                    event.details,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            },
        )

    async def record_credential_failure(
        self,
        normalized_email: str,
        *,
        now: datetime,
    ) -> None:
        await self._required_connection().execute(
            text(
                """
                UPDATE public.users
                SET failed_login_attempts = CASE
                        WHEN locked_until > :now THEN failed_login_attempts
                        WHEN locked_until IS NOT NULL THEN 1
                        ELSE LEAST(failed_login_attempts + 1, 5)
                    END,
                    locked_until = CASE
                        WHEN locked_until > :now THEN locked_until
                        WHEN locked_until IS NOT NULL THEN NULL
                        WHEN failed_login_attempts + 1 >= 5
                            THEN :now + INTERVAL '15 minutes'
                        ELSE locked_until
                    END
                WHERE email = :email
                """
            ),
            {"email": normalized_email, "now": now},
        )

    async def clear_credential_failures(self, normalized_email: str) -> None:
        await self._required_connection().execute(
            text(
                """
                UPDATE public.users
                SET failed_login_attempts = 0,
                    locked_until = NULL
                WHERE email = :email
                  AND (failed_login_attempts <> 0 OR locked_until IS NOT NULL)
                """
            ),
            {"email": normalized_email},
        )

    async def find_by_token_hash(
        self,
        token_hash: bytes,
    ) -> SessionRecord | None:
        connection = self._required_connection()
        await connection.execute(
            text(
                """
                SELECT set_config(
                    'app.current_session_token_hash',
                    :session_token_hash,
                    true
                )
                """
            ),
            {"session_token_hash": token_hash.hex()},
        )
        result = await connection.execute(
            text(
                """
                SELECT
                    id AS session_id,
                    organization_id,
                    user_id,
                    csrf_token_hash,
                    expires_at,
                    last_seen_at,
                    is_revoked,
                    created_at
                FROM public.user_sessions
                LIMIT 1
                """
            )
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        self._loaded_session = (row["session_id"], row["user_id"])
        return SessionRecord(
            session_id=row["session_id"],
            organization_id=row["organization_id"],
            user_id=row["user_id"],
            csrf_token_hash=row["csrf_token_hash"],
            expires_at=row["expires_at"],
            last_seen_at=row["last_seen_at"],
            is_revoked=row["is_revoked"],
            created_at=row["created_at"],
        )

    async def touch_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        last_seen_at: datetime,
        expires_at: datetime,
    ) -> None:
        if self._loaded_session != (session_id, user_id):
            raise RuntimeError("loaded session context is required")
        connection = self._required_connection()
        await connection.execute(
            text(
                "SELECT set_config('app.current_user_id', :user_id, true)"
            ),
            {"user_id": str(user_id)},
        )
        result = await connection.execute(
            text(
                """
                UPDATE public.user_sessions
                SET last_seen_at = :last_seen_at,
                    expires_at = :expires_at
                WHERE id = :session_id
                  AND user_id = :user_id
                  AND NOT is_revoked
                """
            ),
            {
                "session_id": session_id,
                "user_id": user_id,
                "last_seen_at": last_seen_at,
                "expires_at": expires_at,
            },
        )
        if result.rowcount != 1:
            raise RuntimeError("session renewal did not update exactly one row")

    async def revoke_current_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> None:
        if self._loaded_session != (session_id, user_id):
            raise RuntimeError("loaded session context is required")
        result = await self._required_connection().execute(
            text(
                """
                UPDATE public.user_sessions
                SET is_revoked = true
                WHERE id = :session_id
                  AND user_id = :user_id
                  AND NOT is_revoked
                """
            ),
            {"session_id": session_id, "user_id": user_id},
        )
        if result.rowcount != 1:
            raise RuntimeError("session revocation did not update exactly one row")

    async def load_permissions(
        self,
        *,
        user_id: UUID,
        organization_id: UUID,
    ) -> frozenset[str]:
        if self._loaded_session is None or self._loaded_session[1] != user_id:
            raise RuntimeError("loaded session context is required")
        connection = self._required_connection()
        await connection.execute(text("SET LOCAL ROLE nexus_app_user"))
        await connection.execute(
            text(
                "SELECT set_config('app.current_organization_id', :org_id, true)"
            ),
            {"org_id": str(organization_id)},
        )
        result = await connection.execute(
            text(
                """
                SELECT DISTINCT permission.name
                FROM public.user_roles AS assignment
                JOIN public.role_permissions AS role_permission
                  ON role_permission.role_scope_id = assignment.role_scope_id
                 AND role_permission.role_id = assignment.role_id
                JOIN public.permissions AS permission
                  ON permission.id = role_permission.permission_id
                WHERE assignment.organization_id = :organization_id
                  AND assignment.user_id = :user_id
                ORDER BY permission.name
                """
            ),
            {"organization_id": organization_id, "user_id": user_id},
        )
        return frozenset(result.scalars().all())

    async def lock_password_reset_token(
        self,
        token_id: UUID,
    ) -> PasswordResetRecord | None:
        result = await self._required_connection().execute(
            text(
                """
                SELECT
                    id AS token_id,
                    user_id,
                    token_hash,
                    expires_at,
                    used_at,
                    is_revoked
                FROM public.password_reset_tokens
                WHERE id = :token_id
                  AND purpose = 'PASSWORD_RESET'
                FOR UPDATE
                """
            ),
            {"token_id": token_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        self._loaded_password_reset = (row["token_id"], row["user_id"])
        return PasswordResetRecord(
            token_id=row["token_id"],
            user_id=row["user_id"],
            secret_hash=row["token_hash"],
            expires_at=row["expires_at"],
            used_at=row["used_at"],
            is_revoked=row["is_revoked"],
        )

    async def consume_password_reset(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        password_hash: str,
        used_at: datetime,
    ) -> None:
        if self._loaded_password_reset != (token_id, user_id):
            raise RuntimeError("locked password reset context is required")
        connection = self._required_connection()
        user_result = await connection.execute(
            text(
                """
                UPDATE public.users
                SET password_hash = :password_hash,
                    failed_login_attempts = 0,
                    locked_until = NULL
                WHERE id = :user_id
                  AND is_active
                """
            ),
            {"user_id": user_id, "password_hash": password_hash},
        )
        if user_result.rowcount != 1:
            raise RuntimeError("password reset did not update exactly one user")
        token_result = await connection.execute(
            text(
                """
                UPDATE public.password_reset_tokens
                SET used_at = :used_at
                WHERE id = :token_id
                  AND user_id = :user_id
                  AND used_at IS NULL
                  AND NOT is_revoked
                """
            ),
            {"token_id": token_id, "user_id": user_id, "used_at": used_at},
        )
        if token_result.rowcount != 1:
            raise RuntimeError("password reset token was consumed concurrently")
        await connection.execute(
            text(
                """
                UPDATE public.password_reset_tokens
                SET is_revoked = true
                WHERE user_id = :user_id
                  AND id <> :token_id
                  AND used_at IS NULL
                  AND NOT is_revoked
                """
            ),
            {"user_id": user_id, "token_id": token_id},
        )
        await connection.execute(
            text(
                """
                UPDATE public.user_sessions
                SET is_revoked = true
                WHERE user_id = :user_id
                  AND NOT is_revoked
                """
            ),
            {"user_id": user_id},
        )

    async def find_active_reset_user_id(
        self,
        normalized_email: str,
    ) -> UUID | None:
        result = await self._required_connection().execute(
            text(
                """
                SELECT id AS user_id
                FROM public.users
                WHERE email = :email
                  AND is_active
                LIMIT 1
                """
            ),
            {"email": normalized_email},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        self._verified_reset_user_id = row["user_id"]
        return row["user_id"]

    async def replace_password_reset_token(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        if self._verified_reset_user_id != user_id:
            raise RuntimeError("verified reset user context is required")
        connection = self._required_connection()
        await connection.execute(
            text(
                """
                UPDATE public.password_reset_tokens
                SET is_revoked = true
                WHERE user_id = :user_id
                  AND used_at IS NULL
                  AND NOT is_revoked
                """
            ),
            {"user_id": user_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO public.password_reset_tokens (
                    id, user_id, token_hash, purpose, created_at, expires_at
                ) VALUES (
                    :token_id, :user_id, :token_hash, 'PASSWORD_RESET',
                    :created_at, :expires_at
                )
                """
            ),
            {
                "token_id": token_id,
                "user_id": user_id,
                "token_hash": token_hash,
                "created_at": created_at,
                "expires_at": expires_at,
            },
        )
