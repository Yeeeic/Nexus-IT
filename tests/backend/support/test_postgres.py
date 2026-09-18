import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.app.support.postgres import PostgresSupportRepository
from backend.app.support.service import (
    ActionCommand,
    RequestTrace,
    SupportConflict,
    TicketTransitionCommand,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
DEVICE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ACTION_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
NONCE = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
TICKET_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
NOW = datetime(2026, 8, 24, 18, 30, tzinfo=timezone.utc)


class Result:
    def __init__(
        self,
        rows: list[dict[str, object]] | None = None,
        rowcount: int = 0,
    ) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> "Result":
        return self

    def first(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def all(self) -> list[dict[str, object]]:
        return self.rows


class Connection:
    def __init__(self, results: list[Result]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    async def execute(
        self,
        statement: object,
        parameters: dict[str, object] | None = None,
    ) -> Result:
        self.calls.append((str(statement), parameters))
        return self.results.pop(0)


class Transaction:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class Engine:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def begin(self) -> Transaction:
        return Transaction(self.connection)


def action_command() -> ActionCommand:
    return ActionCommand(
        organization_id=ORG_ID,
        id=ACTION_ID,
        device_id=DEVICE_ID,
        action_name="flush_dns",
        requested_by=USER_ID,
        nonce=NONCE,
        key_version=1,
        issued_at=NOW,
        expires_at=NOW.replace(minute=35),
        signature="signed",
        parameters={},
        parameters_canonical="{}",
        status="DISPATCHED",
        trace=RequestTrace("192.0.2.1", "test"),
    )


def test_create_action_sets_tenant_context_and_uses_parameters() -> None:
    connection = Connection([Result(), Result(), Result(), Result()])
    repository = PostgresSupportRepository(Engine(connection))

    asyncio.run(repository.create_action(action_command()))

    assert connection.calls[1][1] == {"organization_id": str(ORG_ID)}
    insert_sql, insert_parameters = connection.calls[2]
    assert "INSERT INTO public.action_executions" in insert_sql
    assert ":action_name" in insert_sql
    assert "flush_dns" not in insert_sql
    assert insert_parameters is not None
    assert insert_parameters["action_name"] == "flush_dns"
    audit_sql, audit_parameters = connection.calls[3]
    assert "INSERT INTO public.audit_logs" in audit_sql
    assert audit_parameters is not None
    assert audit_parameters["action"] == "REMOTE_ACTION.REQUESTED"


def test_ticket_transition_uses_compare_and_swap() -> None:
    connection = Connection([Result(), Result(), Result(rowcount=0)])
    repository = PostgresSupportRepository(Engine(connection))
    command = TicketTransitionCommand(
        organization_id=ORG_ID,
        ticket_id=TICKET_ID,
        actor_id=USER_ID,
        expected_status="NEW",
        target_status="ASSIGNED",
        assigned_to=USER_ID,
        resolved_at=None,
        trace=RequestTrace(None, None),
    )

    with pytest.raises(SupportConflict):
        asyncio.run(repository.transition_ticket(command))

    update_sql, parameters = connection.calls[2]
    assert "status = :expected_status" in update_sql
    assert parameters is not None
    assert parameters["expected_status"] == "NEW"


def test_reader_ticket_queries_are_owner_scoped_in_sql() -> None:
    connection = Connection([Result(), Result(), Result([])])
    repository = PostgresSupportRepository(Engine(connection))

    items, cursor = asyncio.run(
        repository.list_tickets(
            ORG_ID,
            actor_id=USER_ID,
            can_read_all=False,
            limit=25,
            after_id=None,
        )
    )

    assert items == ()
    assert cursor is None
    query, parameters = connection.calls[2]
    assert "(:can_read_all OR created_by = :actor_id)" in query
    assert parameters is not None
    assert parameters["actor_id"] == USER_ID
    assert parameters["can_read_all"] is False


def test_delete_ticket_returns_attachment_paths_for_storage_cleanup() -> None:
    connection = Connection(
        [
            Result(),
            Result(),
            Result(
                [
                    {"id": TICKET_ID, "storage_path": "private/one.png"},
                    {"id": TICKET_ID, "storage_path": "private/two.txt"},
                ]
            ),
            Result(),
        ]
    )
    repository = PostgresSupportRepository(Engine(connection))

    paths = asyncio.run(
        repository.delete_ticket(
            organization_id=ORG_ID,
            ticket_id=TICKET_ID,
            actor_id=USER_ID,
            can_delete_any=True,
            trace=RequestTrace(None, None),
        )
    )

    assert paths == ("private/one.png", "private/two.txt")
    delete_sql, parameters = connection.calls[2]
    assert "deleted_attachments" in delete_sql
    assert "LEFT JOIN deleted_attachments" in delete_sql
    assert parameters is not None
    assert parameters["organization_id"] == ORG_ID


def test_terminal_action_result_replay_does_not_duplicate_audit() -> None:
    digest = b"x" * 32
    connection = Connection(
        [
            Result(),
            Result(),
            Result(rowcount=0),
            Result(
                [
                    {
                        "status": "COMPLETED",
                        "result_digest": digest,
                        "acknowledged_token_id": NONCE,
                    }
                ]
            ),
        ]
    )
    repository = PostgresSupportRepository(Engine(connection))

    replay = asyncio.run(
        repository.record_action_result(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            action_id=ACTION_ID,
            token_id=NONCE,
            status="COMPLETED",
            exit_code=0,
            output_summary="ok",
            result_digest=digest,
            executed_at=NOW,
            trace=RequestTrace("192.0.2.2", "agent"),
        )
    )

    assert replay is True
    assert len(connection.calls) == 4


class Signer:
    key_version = 7

    def __init__(self) -> None:
        self.payload: bytes | None = None

    def sign(self, payload: bytes) -> str:
        self.payload = payload
        return "s" * 86


def test_reboot_is_signed_inside_locked_approval_transaction() -> None:
    signer = Signer()
    connection = Connection(
        [
            Result(),
            Result(),
            Result(
                [
                    {
                        "id": ACTION_ID,
                        "device_id": DEVICE_ID,
                        "action_name": "reboot_system",
                        "requested_by": USER_ID,
                        "nonce": NONCE,
                        "parameters": {"delay_seconds": 0, "force": False},
                        "parameters_canonical": '{"delay_seconds":0,"force":false}',
                    }
                ]
            ),
            Result(rowcount=1),
            Result(),
        ]
    )
    repository = PostgresSupportRepository(Engine(connection))

    approval = asyncio.run(
        repository.approve_action(
            organization_id=ORG_ID,
            action_id=ACTION_ID,
            approver_id=USER_ID,
            now=NOW,
            signer=signer,
            trace=RequestTrace(None, None),
        )
    )

    assert approval.status == "DISPATCHED"
    assert "FOR UPDATE" in connection.calls[2][0]
    assert signer.payload is not None
    assert b"reboot_system\n" in signer.payload
    update_parameters = connection.calls[3][1]
    assert update_parameters is not None
    assert update_parameters["signature"] == "s" * 86
    assert update_parameters["key_version"] == 7


def test_action_ack_replay_requires_same_device_token() -> None:
    connection = Connection(
        [
            Result(),
            Result(),
            Result(rowcount=0),
            Result(
                [
                    {
                        "status": "ACCEPTED",
                        "acknowledged_token_id": NONCE,
                    }
                ]
            ),
        ]
    )
    repository = PostgresSupportRepository(Engine(connection))

    replay = asyncio.run(
        repository.acknowledge_action(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            action_id=ACTION_ID,
            token_id=NONCE,
            now=NOW,
            trace=RequestTrace(None, None),
        )
    )

    assert replay is True
    assert "NOT token.is_revoked" in connection.calls[2][0]
    assert len(connection.calls) == 4
