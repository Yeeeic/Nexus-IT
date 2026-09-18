"""Parameterized PostgreSQL persistence guarded by tenant RLS and CAS."""

from __future__ import annotations

import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from backend.app.support.service import (
    ActionApproval,
    ActionCommand,
    ActionSigner,
    AttachmentCreateCommand,
    AttachmentDeletionOutboxItem,
    AttachmentRecord,
    CommentCreateCommand,
    CommentRecord,
    RequestTrace,
    SupportConflict,
    SupportNotFound,
    TicketCreateCommand,
    TicketRecord,
    TicketTransitionCommand,
    build_action_signing_payload,
)


class PostgresSupportRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def _set_tenant(
        self, connection: AsyncConnection, organization_id: UUID
    ) -> None:
        await connection.execute(text("SET LOCAL ROLE nexus_app_user"))
        await connection.execute(
            text(
                "SELECT set_config("
                "'app.current_organization_id', :organization_id, true)"
            ),
            {"organization_id": str(organization_id)},
        )

    async def _audit(
        self,
        connection: AsyncConnection,
        *,
        organization_id: UUID,
        actor_id: UUID,
        actor_type: str,
        action: str,
        resource_type: str,
        resource_id: UUID,
        status: str = "SUCCESS",
        details: dict[str, str] | None = None,
        trace: RequestTrace,
    ) -> None:
        await connection.execute(
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
                "id": uuid4(),
                "organization_id": organization_id,
                "actor_id": actor_id,
                "actor_type": actor_type,
                "ip_address": trace.ip_address,
                "user_agent": trace.user_agent,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "status": status,
                "details": json.dumps(
                    details or {}, ensure_ascii=True, separators=(",", ":")
                ),
            },
        )

    @staticmethod
    def _ticket(row: dict[str, object]) -> TicketRecord:
        return TicketRecord(
            id=row["id"],
            device_id=row["device_id"],
            alert_id=row["alert_id"],
            created_by=row["created_by"],
            assigned_to=row["assigned_to"],
            ticket_number=row["ticket_number"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            priority=row["priority"],
            resolved_at=row["resolved_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def create_ticket(self, command: TicketCreateCommand) -> TicketRecord:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, command.organization_id)
            result = await connection.execute(
                text(
                    """
                    INSERT INTO public.tickets (
                        organization_id, id, device_id, alert_id, created_by,
                        ticket_number, title, description, priority
                    ) VALUES (
                        :organization_id, :id, :device_id, :alert_id, :created_by,
                        :ticket_number, :title, :description, :priority
                    )
                    RETURNING id, device_id, alert_id, created_by, assigned_to,
                              ticket_number, title, description, status,
                              priority, resolved_at, created_at, updated_at
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "id": command.id,
                    "device_id": command.device_id,
                    "alert_id": command.alert_id,
                    "created_by": command.created_by,
                    "ticket_number": command.ticket_number,
                    "title": command.title,
                    "description": command.description,
                    "priority": command.priority,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise SupportConflict
            await self._audit(
                connection,
                organization_id=command.organization_id,
                actor_id=command.created_by,
                actor_type="USER",
                action="TICKET.CREATED",
                resource_type="ticket",
                resource_id=command.id,
                details={"priority": command.priority},
                trace=command.trace,
            )
            return self._ticket(row)

    async def list_tickets(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        can_read_all: bool,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[TicketRecord, ...], UUID | None]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, device_id, alert_id, created_by, assigned_to,
                           ticket_number, title, description, status,
                           priority, resolved_at, created_at, updated_at
                    FROM public.tickets
                    WHERE (:can_read_all OR created_by = :actor_id)
                      AND (CAST(:after_id AS uuid) IS NULL OR id > CAST(:after_id AS uuid))
                    ORDER BY id
                    LIMIT :fetch_limit
                    """
                ),
                {
                    "actor_id": actor_id,
                    "can_read_all": can_read_all,
                    "after_id": after_id,
                    "fetch_limit": limit + 1,
                },
            )
            rows = result.mappings().all()
        visible = tuple(self._ticket(row) for row in rows[:limit])
        cursor = visible[-1].id if len(rows) > limit and visible else None
        return visible, cursor

    async def get_ticket(
        self,
        organization_id: UUID,
        ticket_id: UUID,
        *,
        actor_id: UUID,
        can_read_all: bool,
    ) -> TicketRecord:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT id, device_id, alert_id, created_by, assigned_to,
                           ticket_number, title, description, status,
                           priority, resolved_at, created_at, updated_at
                    FROM public.tickets
                    WHERE id = :ticket_id
                      AND (:can_read_all OR created_by = :actor_id)
                    """
                ),
                {
                    "ticket_id": ticket_id,
                    "actor_id": actor_id,
                    "can_read_all": can_read_all,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise SupportNotFound
            return self._ticket(row)

    async def delete_ticket(
        self,
        *,
        organization_id: UUID,
        ticket_id: UUID,
        actor_id: UUID,
        can_delete_any: bool,
        trace: RequestTrace,
    ) -> tuple[str, ...]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    WITH deleted_attachments AS (
                        SELECT storage_path
                        FROM public.ticket_attachments
                        WHERE organization_id = :organization_id
                          AND ticket_id = :ticket_id
                    ), deleted_ticket AS (
                        DELETE FROM public.tickets
                        WHERE organization_id = :organization_id
                          AND id = :ticket_id
                          AND (:can_delete_any OR created_by = :actor_id)
                        RETURNING id
                    ), queued_outbox AS (
                        INSERT INTO public.attachment_deletions_outbox (
                            id, organization_id, storage_path, status, attempts, created_at
                        )
                        SELECT
                            gen_random_uuid(),
                            :organization_id,
                            deleted_attachments.storage_path,
                            'PENDING',
                            0,
                            CURRENT_TIMESTAMP
                        FROM deleted_attachments
                        WHERE EXISTS (SELECT 1 FROM deleted_ticket)
                          AND deleted_attachments.storage_path IS NOT NULL
                        RETURNING id, storage_path
                    )
                    SELECT deleted_ticket.id, deleted_attachments.storage_path
                    FROM deleted_ticket
                    LEFT JOIN deleted_attachments ON TRUE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "ticket_id": ticket_id,
                    "actor_id": actor_id,
                    "can_delete_any": can_delete_any,
                },
            )
            rows = result.mappings().all()
            if not rows:
                raise SupportNotFound
            await self._audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                actor_type="USER",
                action="TICKET.DELETED",
                resource_type="ticket",
                resource_id=ticket_id,
                details={},
                trace=trace,
            )
            return tuple(
                str(row["storage_path"])
                for row in rows
                if row.get("storage_path") is not None
            )

    async def add_comment(self, command: CommentCreateCommand) -> CommentRecord:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, command.organization_id)
            result = await connection.execute(
                text(
                    """
                    INSERT INTO public.ticket_comments (
                        organization_id, id, ticket_id, user_id,
                        is_internal, content
                    )
                    SELECT
                        :organization_id, :id, :ticket_id, :user_id,
                        :is_internal, :content
                    WHERE EXISTS (
                        SELECT 1
                        FROM public.tickets AS ticket
                        WHERE ticket.organization_id = :organization_id
                          AND ticket.id = :ticket_id
                          AND (NOT :owner_only OR ticket.created_by = :user_id)
                    )
                    RETURNING id, ticket_id, user_id, is_internal,
                              content, created_at
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "id": command.id,
                    "ticket_id": command.ticket_id,
                    "user_id": command.user_id,
                    "is_internal": command.is_internal,
                    "content": command.content,
                    "owner_only": command.owner_only,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise SupportNotFound
            await self._audit(
                connection,
                organization_id=command.organization_id,
                actor_id=command.user_id,
                actor_type="USER",
                action="TICKET.COMMENT_ADDED",
                resource_type="ticket",
                resource_id=command.ticket_id,
                details={"internal": str(command.is_internal).lower()},
                trace=command.trace,
            )
            return CommentRecord(
                id=row["id"],
                ticket_id=row["ticket_id"],
                user_id=row["user_id"],
                is_internal=row["is_internal"],
                content=row["content"],
                created_at=row["created_at"],
            )

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
    ) -> tuple[tuple[CommentRecord, ...], UUID | None]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT comment.id, comment.ticket_id, comment.user_id,
                           comment.is_internal, comment.content,
                           comment.created_at
                    FROM public.ticket_comments AS comment
                    JOIN public.tickets AS ticket
                      ON ticket.organization_id = comment.organization_id
                     AND ticket.id = comment.ticket_id
                    WHERE comment.organization_id = :organization_id
                      AND comment.ticket_id = :ticket_id
                      AND (:can_read_all OR ticket.created_by = :actor_id)
                      AND (:include_internal OR NOT comment.is_internal)
                      AND (CAST(:after_id AS uuid) IS NULL OR comment.id > CAST(:after_id AS uuid))
                    ORDER BY comment.id
                    LIMIT :fetch_limit
                    """
                ),
                {
                    "organization_id": organization_id,
                    "ticket_id": ticket_id,
                    "actor_id": actor_id,
                    "can_read_all": can_read_all,
                    "include_internal": include_internal,
                    "after_id": after_id,
                    "fetch_limit": limit + 1,
                },
            )
            rows = result.mappings().all()
        visible = tuple(
            CommentRecord(
                id=row["id"],
                ticket_id=row["ticket_id"],
                user_id=row["user_id"],
                is_internal=row["is_internal"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows[:limit]
        )
        cursor = visible[-1].id if len(rows) > limit and visible else None
        return visible, cursor

    async def create_attachment(
        self, command: AttachmentCreateCommand
    ) -> AttachmentRecord:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, command.organization_id)
            result = await connection.execute(
                text(
                    """
                    INSERT INTO public.ticket_attachments (
                        organization_id, id, ticket_id, original_name,
                        stored_filename, mime_type, file_size, storage_path
                    )
                    SELECT :organization_id, :id, :ticket_id, :original_name,
                           :stored_filename, :mime_type, :file_size, :storage_path
                    WHERE EXISTS (
                        SELECT 1
                        FROM public.tickets AS ticket
                        WHERE ticket.organization_id = :organization_id
                          AND ticket.id = :ticket_id
                          AND (NOT :owner_only OR ticket.created_by = :actor_id)
                    )
                    RETURNING id, ticket_id, original_name, stored_filename,
                              mime_type, file_size, storage_path, uploaded_at
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "id": command.id,
                    "ticket_id": command.ticket_id,
                    "actor_id": command.actor_id,
                    "original_name": command.original_name,
                    "stored_filename": command.stored_filename,
                    "mime_type": command.mime_type,
                    "file_size": command.file_size,
                    "storage_path": command.storage_path,
                    "owner_only": command.owner_only,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise SupportNotFound
            await self._audit(
                connection,
                organization_id=command.organization_id,
                actor_id=command.actor_id,
                actor_type="USER",
                action="TICKET.ATTACHMENT_UPLOADED",
                resource_type="ticket_attachment",
                resource_id=command.id,
                details={
                    "mime_type": command.mime_type,
                    "file_size": str(command.file_size),
                },
                trace=command.trace,
            )
            return AttachmentRecord(**dict(row))

    async def get_attachment(
        self,
        organization_id: UUID,
        ticket_id: UUID,
        attachment_id: UUID,
        *,
        actor_id: UUID,
        can_read_all: bool,
    ) -> AttachmentRecord:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    SELECT attachment.id, attachment.ticket_id,
                           attachment.original_name, attachment.stored_filename,
                           attachment.mime_type, attachment.file_size,
                           attachment.storage_path, attachment.uploaded_at
                    FROM public.ticket_attachments AS attachment
                    JOIN public.tickets AS ticket
                      ON ticket.organization_id = attachment.organization_id
                     AND ticket.id = attachment.ticket_id
                    WHERE attachment.organization_id = :organization_id
                      AND attachment.ticket_id = :ticket_id
                      AND attachment.id = :attachment_id
                      AND (:can_read_all OR ticket.created_by = :actor_id)
                    """
                ),
                {
                    "organization_id": organization_id,
                    "ticket_id": ticket_id,
                    "attachment_id": attachment_id,
                    "actor_id": actor_id,
                    "can_read_all": can_read_all,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise SupportNotFound
            return AttachmentRecord(**dict(row))

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
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    WITH deleted_attachment AS (
                        DELETE FROM public.ticket_attachments AS attachment
                        WHERE attachment.organization_id = :organization_id
                          AND attachment.ticket_id = :ticket_id
                          AND attachment.id = :attachment_id
                          AND attachment.storage_path = :expected_storage_path
                          AND EXISTS (
                              SELECT 1
                              FROM public.tickets AS ticket
                              WHERE ticket.organization_id = attachment.organization_id
                                AND ticket.id = attachment.ticket_id
                                AND (NOT :owner_only OR ticket.created_by = :actor_id)
                          )
                        RETURNING attachment.storage_path
                    ), queued_outbox AS (
                        INSERT INTO public.attachment_deletions_outbox (
                            id, organization_id, storage_path, status, attempts, created_at
                        )
                        SELECT
                            gen_random_uuid(),
                            :organization_id,
                            deleted_attachment.storage_path,
                            'PENDING',
                            0,
                            CURRENT_TIMESTAMP
                        FROM deleted_attachment
                        RETURNING id
                    )
                    SELECT deleted_attachment.storage_path
                    FROM deleted_attachment
                    """
                ),
                {
                    "organization_id": organization_id,
                    "ticket_id": ticket_id,
                    "attachment_id": attachment_id,
                    "actor_id": actor_id,
                    "owner_only": owner_only,
                    "expected_storage_path": expected_storage_path,
                },
            )
            rows = result.mappings().all()
            if not rows:
                raise SupportNotFound
            await self._audit(
                connection,
                organization_id=organization_id,
                actor_id=actor_id,
                actor_type="USER",
                action="TICKET.ATTACHMENT_DELETED",
                resource_type="ticket_attachment",
                resource_id=attachment_id,
                trace=trace,
            )

    async def transition_ticket(
        self, command: TicketTransitionCommand
    ) -> TicketTransitionCommand:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, command.organization_id)
            result = await connection.execute(
                text(
                    """
                    UPDATE public.tickets
                    SET status = :target_status,
                        assigned_to = CASE
                            WHEN :target_status = 'ASSIGNED' THEN :assigned_to
                            ELSE assigned_to
                        END,
                        resolved_at = CASE
                            WHEN :target_status = 'RESOLVED' THEN :resolved_at
                            WHEN :target_status = 'IN_PROGRESS' THEN NULL
                            ELSE resolved_at
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = :organization_id
                      AND id = :ticket_id
                      AND status = :expected_status
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "ticket_id": command.ticket_id,
                    "expected_status": command.expected_status,
                    "target_status": command.target_status,
                    "assigned_to": command.assigned_to,
                    "resolved_at": command.resolved_at,
                },
            )
            if result.rowcount != 1:
                raise SupportConflict("Estado de ticket cambió")
            await self._audit(
                connection,
                organization_id=command.organization_id,
                actor_id=command.actor_id,
                actor_type="USER",
                action="TICKET.STATUS_CHANGED",
                resource_type="ticket",
                resource_id=command.ticket_id,
                details={
                    "from": command.expected_status,
                    "to": command.target_status,
                },
                trace=command.trace,
            )
            return command

    async def create_action(self, command: ActionCommand) -> ActionCommand:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, command.organization_id)
            await connection.execute(
                text(
                    """
                    INSERT INTO public.action_executions (
                        organization_id, id, device_id, action_name,
                        requested_by, nonce, key_version, issued_at, expires_at,
                        signature, parameters, parameters_canonical, status
                    ) VALUES (
                        :organization_id, :id, :device_id, :action_name,
                        :requested_by, :nonce, :key_version, :issued_at,
                        :expires_at, :signature, CAST(:parameters AS jsonb),
                        :parameters_canonical, :status
                    )
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "id": command.id,
                    "device_id": command.device_id,
                    "action_name": command.action_name,
                    "requested_by": command.requested_by,
                    "nonce": command.nonce,
                    "key_version": command.key_version,
                    "issued_at": command.issued_at,
                    "expires_at": command.expires_at,
                    "signature": command.signature,
                    "parameters": command.parameters_canonical,
                    "parameters_canonical": command.parameters_canonical,
                    "status": command.status,
                },
            )
            await self._audit(
                connection,
                organization_id=command.organization_id,
                actor_id=command.requested_by,
                actor_type="USER",
                action="REMOTE_ACTION.REQUESTED",
                resource_type="action_execution",
                resource_id=command.id,
                details={
                    "action_name": command.action_name,
                    "status": command.status,
                },
                trace=command.trace,
            )
            return command

    async def approve_action(
        self,
        *,
        organization_id: UUID,
        action_id: UUID,
        approver_id: UUID,
        now: datetime,
        signer: ActionSigner,
        trace: RequestTrace,
    ) -> ActionApproval:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            pending = await connection.execute(
                text(
                    """
                    SELECT id, device_id, action_name, requested_by, nonce,
                           parameters, parameters_canonical
                    FROM public.action_executions
                    WHERE organization_id = :organization_id
                      AND id = :action_id
                      AND status = 'PENDING_APPROVAL'
                      AND expires_at > :now
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "action_id": action_id,
                    "now": now,
                },
            )
            row = pending.mappings().first()
            if row is None:
                raise SupportConflict("Acción no aprobable")
            issued_at = now.astimezone(timezone.utc).replace(microsecond=0)
            expires_at = issued_at + timedelta(minutes=5)
            unsigned = ActionCommand(
                organization_id=organization_id,
                id=row["id"],
                device_id=row["device_id"],
                action_name=row["action_name"],
                requested_by=row["requested_by"],
                nonce=row["nonce"],
                key_version=signer.key_version,
                issued_at=issued_at,
                expires_at=expires_at,
                signature=None,
                parameters=dict(row["parameters"]),
                parameters_canonical=row["parameters_canonical"],
                status="DISPATCHED",
                trace=trace,
            )
            signature = signer.sign(build_action_signing_payload(unsigned))
            result = await connection.execute(
                text(
                    """
                    UPDATE public.action_executions
                    SET status = 'DISPATCHED',
                        approved_by = :approver_id,
                        approved_at = :approved_at,
                        key_version = :key_version,
                        issued_at = :issued_at,
                        expires_at = :expires_at,
                        signature = :signature
                    WHERE organization_id = :organization_id
                      AND id = :action_id
                      AND status = 'PENDING_APPROVAL'
                    """
                ),
                {
                    "organization_id": organization_id,
                    "action_id": action_id,
                    "approver_id": approver_id,
                    "approved_at": now,
                    "key_version": signer.key_version,
                    "issued_at": issued_at,
                    "expires_at": expires_at,
                    "signature": signature,
                },
            )
            if result.rowcount != 1:
                raise SupportConflict("Acción no aprobable")
            await self._audit(
                connection,
                organization_id=organization_id,
                actor_id=approver_id,
                actor_type="USER",
                action="REMOTE_ACTION.APPROVED",
                resource_type="action_execution",
                resource_id=action_id,
                trace=trace,
            )
            return ActionApproval(action_id=action_id, status="DISPATCHED")

    async def poll_actions(
        self,
        organization_id: UUID,
        device_id: UUID,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[ActionCommand, ...]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            await connection.execute(
                text(
                    """
                    UPDATE public.action_executions
                    SET status = 'TIMED_OUT'
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND status = 'DISPATCHED'
                      AND expires_at <= :now
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "now": now,
                },
            )
            result = await connection.execute(
                text(
                    """
                    SELECT id, device_id, action_name, requested_by, nonce,
                           key_version, issued_at, expires_at, signature,
                           parameters, parameters_canonical, status
                    FROM public.action_executions
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND status = 'DISPATCHED'
                      AND expires_at > :now
                      AND signature IS NOT NULL
                    ORDER BY issued_at, id
                    LIMIT :limit
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "now": now,
                    "limit": limit,
                },
            )
            rows = result.mappings().all()
        return tuple(
            ActionCommand(
                organization_id=organization_id,
                id=row["id"],
                device_id=row["device_id"],
                action_name=row["action_name"],
                requested_by=row["requested_by"],
                nonce=row["nonce"],
                key_version=row["key_version"],
                issued_at=row["issued_at"],
                expires_at=row["expires_at"],
                signature=row["signature"],
                parameters=dict(row["parameters"]),
                parameters_canonical=row["parameters_canonical"],
                status=row["status"],
                trace=RequestTrace(None, None),
            )
            for row in rows
        )

    async def acknowledge_action(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        action_id: UUID,
        token_id: UUID,
        now: datetime,
        trace: RequestTrace,
    ) -> bool:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            updated = await connection.execute(
                text(
                    """
                    UPDATE public.action_executions
                    SET status = 'ACCEPTED',
                        acknowledged_token_id = :token_id,
                        accepted_at = :now
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :action_id
                      AND status = 'DISPATCHED'
                      AND expires_at > :now
                      AND signature IS NOT NULL
                      AND EXISTS (
                          SELECT 1
                          FROM public.device_tokens AS token
                          WHERE token.organization_id = :organization_id
                            AND token.device_id = :device_id
                            AND token.id = :token_id
                            AND NOT token.is_revoked
                            AND (token.expires_at IS NULL OR token.expires_at > :now)
                      )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "action_id": action_id,
                    "token_id": token_id,
                    "now": now,
                },
            )
            if updated.rowcount == 1:
                await self._audit(
                    connection,
                    organization_id=organization_id,
                    actor_id=device_id,
                    actor_type="AGENT",
                    action="REMOTE_ACTION.ACCEPTED",
                    resource_type="action_execution",
                    resource_id=action_id,
                    trace=trace,
                )
                return False
            current = await connection.execute(
                text(
                    """
                    SELECT status, acknowledged_token_id
                    FROM public.action_executions
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :action_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "action_id": action_id,
                },
            )
            row = current.mappings().first()
            if row is None:
                raise SupportNotFound
            if row["status"] == "ACCEPTED" and row["acknowledged_token_id"] == token_id:
                return True
            raise SupportConflict("Acción no reconocible")

    async def record_action_result(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        action_id: UUID,
        token_id: UUID,
        status: str,
        exit_code: int | None,
        output_summary: str | None,
        result_digest: bytes,
        executed_at: datetime,
        trace: RequestTrace,
    ) -> bool:
        allowed_sources = {
            "ACCEPTED": ("ACCEPTED",),
            "EXECUTING": ("ACCEPTED",),
            "COMPLETED": ("ACCEPTED", "EXECUTING"),
            "FAILED": ("ACCEPTED", "EXECUTING"),
            "INTERRUPTED": ("ACCEPTED", "EXECUTING"),
            "UNKNOWN": ("ACCEPTED", "EXECUTING"),
        }[status]
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            updated = await connection.execute(
                text(
                    """
                    UPDATE public.action_executions
                    SET status = :status,
                        exit_code = :exit_code,
                        output_summary = :output_summary,
                        result_digest = :result_digest,
                        executed_at = CASE
                            WHEN :is_terminal THEN :executed_at
                            ELSE executed_at
                        END
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :action_id
                      AND acknowledged_token_id = :token_id
                      AND status = ANY(:allowed_sources)
                      AND EXISTS (
                          SELECT 1
                          FROM public.device_tokens AS token
                          WHERE token.organization_id = :organization_id
                            AND token.device_id = :device_id
                            AND token.id = :token_id
                            AND NOT token.is_revoked
                            AND (token.expires_at IS NULL OR token.expires_at > :executed_at)
                      )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "action_id": action_id,
                    "token_id": token_id,
                    "status": status,
                    "exit_code": exit_code,
                    "output_summary": output_summary,
                    "result_digest": result_digest,
                    "executed_at": executed_at,
                    "is_terminal": status
                    in {"COMPLETED", "FAILED", "INTERRUPTED", "UNKNOWN"},
                    "allowed_sources": list(allowed_sources),
                },
            )
            if updated.rowcount == 1:
                await self._audit(
                    connection,
                    organization_id=organization_id,
                    actor_id=device_id,
                    actor_type="AGENT",
                    action="REMOTE_ACTION.RESULT_RECORDED",
                    resource_type="action_execution",
                    resource_id=action_id,
                    details={"status": status},
                    trace=trace,
                )
                return False
            current = await connection.execute(
                text(
                    """
                    SELECT status, result_digest, acknowledged_token_id
                    FROM public.action_executions
                    WHERE organization_id = :organization_id
                      AND device_id = :device_id
                      AND id = :action_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "device_id": device_id,
                    "action_id": action_id,
                },
            )
            row = current.mappings().first()
            if row is None:
                raise SupportNotFound
            stored_digest = row["result_digest"]
            if (
                row["status"] == status
                and row["acknowledged_token_id"] == token_id
                and stored_digest is not None
                and hmac.compare_digest(stored_digest, result_digest)
            ):
                return True
            raise SupportConflict("Regresión o resultado diferente")

    async def claim_pending_attachment_deletions(
        self,
        organization_id: UUID,
        *,
        batch_size: int = 20,
    ) -> tuple[AttachmentDeletionOutboxItem, ...]:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            result = await connection.execute(
                text(
                    """
                    UPDATE public.attachment_deletions_outbox
                    SET status = 'PROCESSING'
                    WHERE id IN (
                        SELECT id
                        FROM public.attachment_deletions_outbox
                        WHERE organization_id = :organization_id
                          AND status IN ('PENDING', 'FAILED')
                          AND attempts < max_attempts
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT :batch_size
                    )
                    RETURNING id, organization_id, storage_path, status, attempts, max_attempts, created_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "batch_size": batch_size,
                },
            )
            rows = result.mappings().all()
            return tuple(
                AttachmentDeletionOutboxItem(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    storage_path=row["storage_path"],
                    status=row["status"],
                    attempts=row["attempts"],
                    max_attempts=row["max_attempts"],
                    created_at=row["created_at"],
                )
                for row in rows
            )

    async def mark_attachment_deletion_completed(
        self,
        organization_id: UUID,
        outbox_id: UUID,
    ) -> None:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            await connection.execute(
                text(
                    """
                    UPDATE public.attachment_deletions_outbox
                    SET status = 'COMPLETED', processed_at = CURRENT_TIMESTAMP
                    WHERE organization_id = :organization_id
                      AND id = :outbox_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "outbox_id": outbox_id,
                },
            )

    async def mark_attachment_deletion_failed(
        self,
        organization_id: UUID,
        outbox_id: UUID,
        error_summary: str,
    ) -> None:
        async with self._engine.begin() as connection:
            await self._set_tenant(connection, organization_id)
            await connection.execute(
                text(
                    """
                    UPDATE public.attachment_deletions_outbox
                    SET status = CASE WHEN attempts + 1 >= max_attempts THEN 'FAILED' ELSE 'PENDING' END,
                        attempts = attempts + 1,
                        last_error = :error_summary,
                        processed_at = CURRENT_TIMESTAMP
                    WHERE organization_id = :organization_id
                      AND id = :outbox_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "outbox_id": outbox_id,
                    "error_summary": error_summary[:1000],
                },
            )
