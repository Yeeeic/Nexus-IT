import asyncio
from uuid import UUID

from backend.app.users.postgres import PostgresUserDirectory


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_A = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
USER_B = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
USER_C = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


class Result:
    def __init__(
        self,
        rows: list[dict[str, object]] | None = None,
        *,
        rowcount: int = 0,
    ) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> "Result":
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def one(self) -> dict[str, object]:
        assert len(self.rows) == 1
        return self.rows[0]


class Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.results = [
            Result(),
            Result(),
            Result(
                [
                    {
                        "id": USER_A,
                        "email": "a@example.test",
                        "full_name": "A",
                        "is_active": True,
                    },
                    {
                        "id": USER_B,
                        "email": "b@example.test",
                        "full_name": "B",
                        "is_active": True,
                    },
                    {
                        "id": USER_C,
                        "email": "c@example.test",
                        "full_name": "C",
                        "is_active": True,
                    },
                ]
            ),
        ]

    async def execute(
        self,
        statement: object,
        parameters: dict[str, object] | None = None,
    ) -> Result:
        self.calls.append((str(statement), parameters))
        return self.results.pop(0)


class TransactionContext:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class Engine:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def begin(self) -> TransactionContext:
        return TransactionContext(self.connection)


def test_directory_sets_rls_context_and_uses_bounded_keyset_pagination() -> None:
    connection = Connection()
    directory = PostgresUserDirectory(Engine(connection))

    items, next_cursor = asyncio.run(
        directory.list_users(ORG_ID, actor_id=USER_A, limit=2, after_id=None)
    )

    assert [item.id for item in items] == [USER_A, USER_B]
    assert next_cursor == USER_B
    assert connection.calls[1][1] == {"organization_id": str(ORG_ID)}
    assert connection.calls[2][1] == {
        "organization_id": ORG_ID,
        "actor_id": USER_A,
        "after_id": None,
        "fetch_limit": 3,
    }
    sql = "\n".join(statement for statement, _ in connection.calls)
    assert str(ORG_ID) not in sql
    assert "public.list_tenant_users" in sql


def test_create_user_uses_narrow_function_and_appends_sanitized_audit() -> None:
    connection = Connection()
    connection.results = [
        Result(),
        Result(),
        Result(
            [
                {
                    "id": USER_B,
                    "email": "member@example.test",
                    "full_name": "Existing Name",
                    "is_active": True,
                }
            ]
        ),
        Result(rowcount=1),
    ]
    directory = PostgresUserDirectory(Engine(connection))

    created = asyncio.run(
        directory.create_user(
            ORG_ID,
            actor_id=USER_A,
            ip_address="192.0.2.10",
            user_agent="Browser/1.0",
            email="member@example.test",
            full_name="Attempted Replacement",
            password_hash="$argon2id$must-not-be-audited",
            role_name="ADMIN",
        )
    )

    assert created.id == USER_B
    sql = "\n".join(statement for statement, _ in connection.calls)
    assert "SET LOCAL ROLE nexus_app_user" in sql
    assert "SET LOCAL ROLE nexus_admin" not in sql
    assert "public.create_tenant_user_membership" in sql
    assert "ON CONFLICT (email) DO UPDATE" not in sql
    assert "INSERT INTO public.audit_logs" in sql
    audit_parameters = connection.calls[-1][1]
    assert audit_parameters is not None
    assert audit_parameters["actor_id"] == USER_A
    assert audit_parameters["ip_address"] == "192.0.2.10"
    assert audit_parameters["user_agent"] == "Browser/1.0"
    assert "$argon2id$" not in str(audit_parameters["details"])


def test_membership_mutations_are_tenant_scoped_and_audited() -> None:
    cases = (
        (
            "toggle_user_active",
            {"user_id": USER_B, "is_active": False},
            "public.set_tenant_user_membership_active",
            "USER.MEMBERSHIP_STATUS_CHANGED",
        ),
        (
            "revoke_user_sessions",
            {"user_id": USER_B},
            "public.revoke_tenant_user_sessions",
            "USER.SESSIONS_REVOKED",
        ),
        (
            "delete_user",
            {"user_id": USER_B},
            "public.delete_tenant_user_membership",
            "USER.MEMBERSHIP_DELETED",
        ),
    )

    for method_name, operation_parameters, function_name, action in cases:
        connection = Connection()
        operation_row: dict[str, object]
        if method_name == "toggle_user_active":
            operation_row = {
                "id": USER_B,
                "email": "member@example.test",
                "full_name": "Member",
                "is_active": False,
            }
        elif method_name == "revoke_user_sessions":
            operation_row = {"revoked_count": 2}
        else:
            operation_row = {"deleted": True}
        connection.results = [
            Result(),
            Result(),
            Result([operation_row]),
            Result(rowcount=1),
        ]
        directory = PostgresUserDirectory(Engine(connection))
        method = getattr(directory, method_name)

        result = asyncio.run(
            method(
                ORG_ID,
                actor_id=USER_A,
                ip_address=None,
                user_agent=None,
                **operation_parameters,
            )
        )

        assert result is not None
        sql = "\n".join(statement for statement, _ in connection.calls)
        assert function_name in sql
        assert "SET LOCAL ROLE nexus_admin" not in sql
        assert "INSERT INTO public.audit_logs" in sql
        assert connection.calls[-1][1]["action"] == action
