import asyncio
from datetime import UTC, datetime
from uuid import UUID

from backend.app.administration.postgres import PostgresAdministration


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ROLE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
AUDIT_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)


class Result:
    def __init__(
        self,
        rows: list[dict[str, object]] | None = None,
        *,
        rowcount: int = 1,
        one: dict[str, object] | None = None,
    ) -> None:
        self.rows = rows or []
        self.rowcount = rowcount
        self.one = one

    def mappings(self) -> "Result":
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def one_or_none(self) -> dict[str, object] | None:
        return self.one


class Connection:
    def __init__(self, results: list[Result]) -> None:
        self.results = results
        self.calls: list[tuple[str, object]] = []

    async def execute(self, statement: object, parameters: object = None) -> Result:
        self.calls.append((str(statement), parameters))
        return self.results.pop(0)


class Context:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class Engine:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def begin(self) -> Context:
        return Context(self.connection)


def test_lists_roles_and_audits_under_bound_tenant_context() -> None:
    connection = Connection(
        [
            Result(), Result(),
            Result([{"id": ROLE_ID, "name": "ADMIN", "description": "Admin", "is_system": True, "permissions": ["users:manage"]}]),
            Result(), Result(),
            Result([{"id": AUDIT_ID, "actor_id": USER_ID, "actor_type": "USER", "action": "RBAC.ROLE_CREATED", "resource_type": "ROLE", "resource_id": ROLE_ID, "status": "SUCCESS", "details": {"name": "HELPDESK"}, "created_at": NOW}]),
        ]
    )
    administration = PostgresAdministration(Engine(connection))

    roles = asyncio.run(administration.list_roles(ORG_ID))
    audits = asyncio.run(administration.list_audit_logs(organization_id=ORG_ID, limit=50, before=None, action=None))

    assert roles[0].permissions == ("users:manage",)
    assert audits[0].action == "RBAC.ROLE_CREATED"
    assert connection.calls[1][1] == {"organization_id": str(ORG_ID)}
    assert connection.calls[4][1] == {"organization_id": str(ORG_ID)}
    sql = "\n".join(call[0] for call in connection.calls)
    assert str(ORG_ID) not in sql


def test_creates_custom_role_and_assignment_with_audit_in_same_transactions() -> None:
    connection = Connection(
        [
            Result(), Result(), Result(rowcount=1), Result(rowcount=1), Result(),
            Result(), Result(), Result(one={"scope_id": ORG_ID}), Result(one={"user_id": USER_ID}), Result(rowcount=1), Result(),
        ]
    )
    administration = PostgresAdministration(
        Engine(connection),
        id_factory=iter([ROLE_ID, AUDIT_ID, AUDIT_ID]).__next__,
        clock=lambda: NOW,
    )

    role = asyncio.run(administration.create_role(organization_id=ORG_ID, actor_id=USER_ID, name="HELPDESK", description="Help desk", permissions=("tickets:read",)))
    asyncio.run(administration.assign_role(organization_id=ORG_ID, actor_id=USER_ID, role_id=ROLE_ID, user_id=USER_ID))

    assert role.id == ROLE_ID
    sql = "\n".join(call[0] for call in connection.calls)
    assert "INSERT INTO public.roles" in sql
    assert "INSERT INTO public.role_permissions" in sql
    assert "INSERT INTO public.user_roles" in sql
    assert sql.count("INSERT INTO public.audit_logs") == 2
