"""PostgreSQL tenant administration under forced RLS."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.administration.service import (
    AdministrationRejected,
    AuditLogSummary,
    RoleSummary,
)


class PostgresAdministration:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._engine = engine
        self._id_factory = id_factory
        self._clock = clock

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
        action: str,
        resource_id: UUID,
        details: dict[str, str],
    ) -> None:
        await connection.execute(  # type: ignore[attr-defined]
            text(
                """
                INSERT INTO public.audit_logs (
                    id, organization_id, actor_id, actor_type, action,
                    resource_type, resource_id, status, details
                ) VALUES (
                    :id, :organization_id, :actor_id, 'USER', :action,
                    'ROLE', :resource_id, 'SUCCESS', CAST(:details AS jsonb)
                )
                """
            ),
            {
                "id": self._id_factory(),
                "organization_id": organization_id,
                "actor_id": actor_id,
                "action": action,
                "resource_id": resource_id,
                "details": json.dumps(details, separators=(",", ":")),
            },
        )

    async def list_roles(self, organization_id: UUID) -> tuple[RoleSummary, ...]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT
                        role.id,
                        role.name,
                        role.description,
                        role.is_system,
                        COALESCE(
                            array_agg(permission.name ORDER BY permission.name)
                                FILTER (WHERE permission.name IS NOT NULL),
                            ARRAY[]::varchar[]
                        ) AS permissions
                    FROM public.roles AS role
                    LEFT JOIN public.role_permissions AS role_permission
                      ON role_permission.role_scope_id = role.scope_id
                     AND role_permission.role_id = role.id
                    LEFT JOIN public.permissions AS permission
                      ON permission.id = role_permission.permission_id
                    GROUP BY role.id, role.name, role.description, role.is_system
                    ORDER BY role.is_system DESC, role.name, role.id
                    """
                )
            )
            rows = result.mappings().all()
        return tuple(
            RoleSummary(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                is_system=row["is_system"],
                permissions=tuple(row["permissions"]),
            )
            for row in rows
        )

    async def create_role(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        name: str,
        description: str,
        permissions: tuple[str, ...],
    ) -> RoleSummary:
        role_id = self._id_factory()
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            await connection.execute(
                text(
                    """
                    INSERT INTO public.roles (
                        id, organization_id, name, description, is_system
                    ) VALUES (
                        :role_id, :organization_id, :name, :description, false
                    )
                    """
                ),
                {
                    "role_id": role_id,
                    "organization_id": organization_id,
                    "name": name,
                    "description": description,
                },
            )
            permission_result = await connection.execute(
                text(
                    """
                    INSERT INTO public.role_permissions (
                        role_scope_id, role_id, permission_id
                    )
                    SELECT :organization_id, :role_id, permission.id
                    FROM public.permissions AS permission
                    WHERE permission.name = ANY(:permissions)
                    """
                ),
                {
                    "organization_id": organization_id,
                    "role_id": role_id,
                    "permissions": list(permissions),
                },
            )
            if permission_result.rowcount != len(permissions):
                raise AdministrationRejected
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                action="RBAC.ROLE_CREATED",
                resource_id=role_id,
                details={"name": name},
            )
        return RoleSummary(role_id, name, description, False, permissions)

    async def assign_role(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        role_id: UUID,
        user_id: UUID,
    ) -> None:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            role_result = await connection.execute(
                text(
                    """
                    SELECT scope_id
                    FROM public.roles
                    WHERE id = :role_id
                      AND (organization_id IS NULL OR organization_id = :organization_id)
                    """
                ),
                {"role_id": role_id, "organization_id": organization_id},
            )
            role = role_result.mappings().one_or_none()
            member_result = await connection.execute(
                text(
                    """
                    SELECT user_id
                    FROM public.organization_memberships
                    WHERE organization_id = :organization_id
                      AND user_id = :user_id
                      AND is_active
                    """
                ),
                {"organization_id": organization_id, "user_id": user_id},
            )
            if role is None or member_result.mappings().one_or_none() is None:
                raise AdministrationRejected
            await connection.execute(
                text(
                    """
                    INSERT INTO public.user_roles (
                        organization_id, user_id, role_scope_id, role_id
                    ) VALUES (
                        :organization_id, :user_id, :role_scope_id, :role_id
                    )
                    ON CONFLICT (organization_id, user_id, role_id) DO NOTHING
                    """
                ),
                {
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "role_scope_id": role["scope_id"],
                    "role_id": role_id,
                },
            )
            await self._append_audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                action="RBAC.ROLE_ASSIGNED",
                resource_id=role_id,
                details={"user_id": str(user_id)},
            )

    async def list_audit_logs(
        self,
        *,
        organization_id: UUID,
        limit: int,
        before: datetime | None,
        action: str | None,
    ) -> tuple[AuditLogSummary, ...]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT
                        id, actor_id, actor_type, action, resource_type,
                        resource_id, status, details, created_at
                    FROM public.audit_logs
                    WHERE organization_id = :organization_id
                      AND (CAST(:before AS timestamptz) IS NULL OR created_at < CAST(:before AS timestamptz))
                      AND (CAST(:action AS text) IS NULL OR action = CAST(:action AS text))
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {
                    "organization_id": organization_id,
                    "before": before,
                    "action": action,
                    "limit": limit,
                },
            )
            rows = result.mappings().all()
        return tuple(AuditLogSummary(**row) for row in rows)
