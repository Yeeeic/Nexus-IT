import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.app.devices.postgres import (
    PostgresAgentTokenRepository,
    PostgresDeviceService,
)
from backend.app.devices.service import (
    AgentIdentity,
    AuditContext,
    DeviceConflict,
    DeviceEnrollment,
    DeviceTokenRecord,
    InventorySnapshotWrite,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
TOKEN_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ACTOR_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
AUDIT_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
NOW = datetime(2026, 8, 24, tzinfo=UTC)


class Result:
    def __init__(self, row=None, rows=None, rowcount=1) -> None:
        self.row = row
        self.rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def all(self):
        return self.rows


class Transaction:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class Connection:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.calls = []
        self.transaction = Transaction()
        self.closed = False

    async def begin(self):
        return self.transaction

    async def execute(self, statement, parameters=None):
        self.calls.append((str(statement), parameters))
        return self.results.pop(0)

    async def close(self):
        self.closed = True


class BeginContext:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class Engine:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def connect(self):
        return self.connection

    def begin(self):
        return BeginContext(self.connection)


def device_row():
    return {
        "organization_id": ORG_ID,
        "id": DEVICE_ID,
        "hostname": "host-1",
        "display_name": "Desk",
        "is_active": True,
        "last_seen_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_agent_repository_uses_public_id_then_activates_composite_tenant() -> None:
    connection = Connection(
        [
            Result(),
            Result(
                row={
                    "token_id": TOKEN_ID,
                    "organization_id": ORG_ID,
                    "device_id": DEVICE_ID,
                    "token_hash": b"h" * 32,
                    "expires_at": NOW + timedelta(days=1),
                    "is_revoked": False,
                }
            ),
            Result(),
            Result(),
            Result(row={"active": True}),
            Result(rowcount=1),
        ]
    )
    repository = PostgresAgentTokenRepository(Engine(connection))

    async def scenario():
        async with repository:
            record = await repository.find_token(TOKEN_ID)
            assert record is not None
            assert await repository.activate_identity(record, used_at=NOW)
            return record

    record = asyncio.run(scenario())

    assert record == DeviceTokenRecord(
        TOKEN_ID,
        ORG_ID,
        DEVICE_ID,
        b"h" * 32,
        NOW + timedelta(days=1),
        False,
    )
    assert connection.transaction.committed
    sql = "\n".join(call[0] for call in connection.calls)
    assert "SET LOCAL ROLE nexus_auth_user" in sql
    assert "SET LOCAL ROLE nexus_app_user" in sql
    assert str(ORG_ID) not in sql
    assert str(DEVICE_ID) not in sql
    assert connection.calls[1][1] == {"token_id": TOKEN_ID}
    assert connection.calls[3][1] == {"organization_id": str(ORG_ID)}


def test_enrollment_persists_only_hash_and_sets_rls_context() -> None:
    connection = Connection(
        [Result(), Result(), Result(row=device_row()), Result(), Result()]
    )
    identifiers = iter([DEVICE_ID, AUDIT_ID])
    service = PostgresDeviceService(
        Engine(connection),
        pepper=b"p" * 32,
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )

    result = asyncio.run(
        service.enroll(
            ORG_ID,
            ACTOR_ID,
            DeviceEnrollment("host-1", "Desk", NOW + timedelta(days=30)),
            AuditContext("127.0.0.1", "pytest"),
        )
    )

    assert result.device.id == DEVICE_ID
    all_parameters = [parameters or {} for _, parameters in connection.calls]
    token_parameters = all_parameters[3]
    assert token_parameters["token_hash"] != result.token.encode()
    assert result.token not in repr(all_parameters)
    assert all_parameters[1] == {"organization_id": str(ORG_ID)}
    assert all_parameters[4]["details"] == "{}"


def test_scoped_device_list_filters_by_actor_assignment() -> None:
    connection = Connection([Result(), Result(), Result(rows=[device_row()])])
    service = PostgresDeviceService(Engine(connection), pepper=b"p" * 32)

    devices, cursor = asyncio.run(
        service.list_devices(
            ORG_ID,
            actor_id=ACTOR_ID,
            assigned_only=True,
            limit=10,
            after_id=None,
        )
    )

    assert devices[0].id == DEVICE_ID
    assert cursor is None
    query, parameters = connection.calls[2]
    assert "device_assignments" in query
    assert parameters["actor_id"] == ACTOR_ID
    assert parameters["assigned_only"] is True


def test_inventory_upsert_revalidates_token_and_uses_composite_identity() -> None:
    inventory_row = {
        "organization_id": ORG_ID,
        "device_id": DEVICE_ID,
        "hardware": {"memory_bytes": 1024},
        "software_packages": [],
        "patches": [],
        "services": [],
        "collected_at": NOW,
        "updated_at": NOW,
    }
    connection = Connection(
        [Result(), Result(), Result(row={"active": True}), Result(row=inventory_row), Result()]
    )
    service = PostgresDeviceService(
        Engine(connection), pepper=b"p" * 32, clock=lambda: NOW
    )
    identity = AgentIdentity(ORG_ID, DEVICE_ID, TOKEN_ID)

    result = asyncio.run(
        service.write_inventory(
            identity,
            InventorySnapshotWrite(
                hardware={"memory_bytes": 1024},
                software_packages=(),
                patches=(),
                services=(),
                collected_at=NOW,
            ),
        )
    )

    assert result.device_id == DEVICE_ID
    token_parameters = connection.calls[2][1]
    assert token_parameters == {
        "organization_id": ORG_ID,
        "device_id": DEVICE_ID,
        "token_id": TOKEN_ID,
        "now": NOW,
    }
    upsert_parameters = connection.calls[3][1]
    assert upsert_parameters["organization_id"] == ORG_ID
    assert upsert_parameters["device_id"] == DEVICE_ID
    sql = connection.calls[3][0]
    assert "ON CONFLICT (organization_id, device_id)" in sql
    assert "EXCLUDED.collected_at >= public.device_inventory.collected_at" in sql


def test_inventory_rejects_far_future_collection_time_before_database() -> None:
    connection = Connection([])
    service = PostgresDeviceService(
        Engine(connection), pepper=b"p" * 32, clock=lambda: NOW
    )

    with pytest.raises(DeviceConflict, match="collection time"):
        asyncio.run(
            service.write_inventory(
                AgentIdentity(ORG_ID, DEVICE_ID, TOKEN_ID),
                InventorySnapshotWrite(
                    hardware={"memory_bytes": 1024},
                    software_packages=(),
                    patches=(),
                    services=(),
                    collected_at=NOW + timedelta(minutes=6),
                ),
            )
        )

    assert connection.calls == []
