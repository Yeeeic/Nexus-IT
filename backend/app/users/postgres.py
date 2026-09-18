"""Async PostgreSQL user directory constrained by tenant RLS."""

import json
from collections.abc import Callable
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.users.service import UserSummary


class PostgresUserDirectory:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._engine = engine
        self._id_factory = id_factory

    async def _set_tenant(self, connection: object, organization_id: UUID) -> None:
        await connection.execute(text("SET LOCAL ROLE nexus_app_user"))  # type: ignore[attr-defined]
        await connection.execute(  # type: ignore[attr-defined]
            text(
                "SELECT set_config("
                "'app.current_organization_id', :organization_id, true)"
            ),
            {"organization_id": str(organization_id)},
        )

    async def _append_audit(
        self,
        connection: object,
        *,
        organization_id: UUID,
        actor_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        action: str,
        resource_id: UUID,
        details: dict[str, object],
    ) -> None:
        await connection.execute(  # type: ignore[attr-defined]
            text(
                """
                INSERT INTO public.audit_logs (
                    id, organization_id, actor_id, actor_type, ip_address,
                    user_agent, action, resource_type, resource_id, status, details
                ) VALUES (
                    :id, :organization_id, :actor_id, 'USER',
                    CAST(:ip_address AS inet), :user_agent, :action,
                    'USER_MEMBERSHIP', :resource_id, 'SUCCESS',
                    CAST(:details AS jsonb)
                )
                """
            ),
            {
                "id": self._id_factory(),
                "organization_id": organization_id,
                "actor_id": actor_id,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "action": action,
                "resource_id": str(resource_id),
                "details": json.dumps(details, separators=(",", ":"), sort_keys=True),
            },
        )

    async def list_users(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[UserSummary, ...], UUID | None]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, email, full_name, is_active
                    FROM public.list_tenant_users(
                        :organization_id, :actor_id, :after_id, :fetch_limit
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "actor_id": actor_id,
                    "after_id": after_id,
                    "fetch_limit": limit + 1,
                },
            )
            rows = result.mappings().all()

        visible_rows = rows[:limit]
        items = tuple(UserSummary(**row) for row in visible_rows)
        next_cursor = items[-1].id if len(rows) > limit and items else None
        return items, next_cursor

    async def create_user(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        email: str,
        full_name: str,
        password_hash: str,
        role_name: str,
    ) -> UserSummary:
        normalized_email = email.strip().lower()
        clean_full_name = full_name.strip()
        normalized_role = role_name.upper()
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, email, full_name, is_active
                    FROM public.create_tenant_user_membership(
                        :organization_id, :actor_id, :new_user_id, :email,
                        :password_hash, :full_name, :role_name
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "actor_id": actor_id,
                    "new_user_id": self._id_factory(),
                    "email": normalized_email,
                    "password_hash": password_hash,
                    "full_name": clean_full_name,
                    "role_name": normalized_role,
                },
            )
            row = result.mappings().one()
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                ip_address=ip_address,
                user_agent=user_agent,
                action="USER.MEMBERSHIP_CREATED",
                resource_id=row["id"],
                details={"email": row["email"], "role": normalized_role},
            )
        return UserSummary(**row)

    async def toggle_user_active(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        user_id: UUID,
        is_active: bool,
    ) -> UserSummary:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, email, full_name, is_active
                    FROM public.set_tenant_user_membership_active(
                        :organization_id, :actor_id, :user_id, :is_active
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "actor_id": actor_id,
                    "user_id": user_id,
                    "is_active": is_active,
                },
            )
            row = result.mappings().one()
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                ip_address=ip_address,
                user_agent=user_agent,
                action="USER.MEMBERSHIP_STATUS_CHANGED",
                resource_id=user_id,
                details={"is_active": is_active},
            )
        return UserSummary(**row)

    async def revoke_user_sessions(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        user_id: UUID,
    ) -> int:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT public.revoke_tenant_user_sessions(
                        :organization_id, :actor_id, :user_id
                    ) AS revoked_count
                    """
                ),
                {
                    "organization_id": organization_id,
                    "actor_id": actor_id,
                    "user_id": user_id,
                },
            )
            revoked_count = int(result.mappings().one()["revoked_count"])
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                ip_address=ip_address,
                user_agent=user_agent,
                action="USER.SESSIONS_REVOKED",
                resource_id=user_id,
                details={"revoked_sessions": revoked_count},
            )
        return revoked_count

    async def delete_user(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        user_id: UUID,
    ) -> bool:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT public.delete_tenant_user_membership(
                        :organization_id, :actor_id, :user_id
                    ) AS deleted
                    """
                ),
                {
                    "organization_id": organization_id,
                    "actor_id": actor_id,
                    "user_id": user_id,
                },
            )
            deleted = bool(result.mappings().one()["deleted"])
            if deleted:
                await self._append_audit(
                    connection,
                    organization_id=organization_id,
                    actor_id=actor_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    action="USER.MEMBERSHIP_DELETED",
                    resource_id=user_id,
                    details={},
                )
        return deleted
