import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.app.audit import AuditEvent
from backend.app.auth.login import SessionCreation
from backend.app.auth.postgres import PostgresLoginRepository
from backend.app.auth.password_reset import PasswordResetRecord


USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ORG_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
SESSION_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)


class FakeResult:
    def __init__(
        self,
        *,
        one: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
        rowcount: int = 1,
        scalar_values: list[str] | None = None,
    ) -> None:
        self.one = one
        self.rows = rows or []
        self.rowcount = rowcount
        self.scalar_values = scalar_values or []

    def mappings(self) -> "FakeResult":
        return self

    def one_or_none(self) -> dict[str, object] | None:
        return self.one

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def scalars(self) -> "FakeScalars":
        return FakeScalars(self.scalar_values)


class FakeScalars:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def all(self) -> list[str]:
        return self.values


class FakeTransaction:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeConnection:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.transaction = FakeTransaction()
        self.closed = False

    async def begin(self) -> FakeTransaction:
        return self.transaction

    async def execute(
        self,
        statement: object,
        parameters: dict[str, object] | None = None,
    ) -> FakeResult:
        self.calls.append((str(statement), parameters))
        return self.results.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def connect(self) -> FakeConnection:
        return self.connection


def test_repository_uses_one_transaction_and_bound_parameters() -> None:
    connection = FakeConnection(
        [
            FakeResult(),
            FakeResult(
                one={
                    "user_id": USER_ID,
                    "password_hash": "$argon2id$test",
                    "is_active": True,
                    "locked_until": None,
                }
            ),
            FakeResult(),
            FakeResult(
                rows=[
                    {
                        "organization_id": ORG_ID,
                        "organization_name": "Org A",
                    }
                ]
            ),
            FakeResult(),
            FakeResult(),
            FakeResult(),
            FakeResult(),
        ]
    )
    repository = PostgresLoginRepository(FakeEngine(connection))
    creation = SessionCreation(
        session_id=SESSION_ID,
        user_id=USER_ID,
        organization_id=ORG_ID,
        session_token_hash=b"a" * 32,
        csrf_token_hash=b"b" * 32,
        expires_at=NOW + timedelta(hours=1),
        last_seen_at=NOW,
        user_agent="Browser/1.0",
        ip_address="192.0.2.10",
    )

    async def exercise() -> None:
        async with repository:
            credential = await repository.find_by_email("user@example.test")
            memberships = await repository.list_active_for_user(USER_ID)
            await repository.replace_for_login(
                creation,
                previous_token_hash=b"c" * 32,
            )
            await repository.append_audit(
                AuditEvent(
                    id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
                    organization_id=ORG_ID,
                    actor_id=USER_ID,
                    actor_type="USER",
                    ip_address="192.0.2.10",
                    user_agent="Browser/1.0",
                    action="AUTH.LOGIN_SUCCESS",
                    resource_type="USER",
                    resource_id=USER_ID,
                    status="SUCCESS",
                    details={"result": "AUTHENTICATED"},
                )
            )

        assert credential is not None
        assert credential.user_id == USER_ID
        assert memberships[0].organization_id == ORG_ID

    asyncio.run(exercise())

    assert connection.transaction.committed is True
    assert connection.transaction.rolled_back is False
    assert connection.closed is True
    all_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "user@example.test" not in all_sql
    assert "192.0.2.10" not in all_sql
    assert any(
        parameters == {"email": "user@example.test"}
        for _, parameters in connection.calls
    )
    assert any(
        parameters and parameters.get("previous_token_hash") == (b"c" * 32).hex()
        for _, parameters in connection.calls
    )


def test_repository_rolls_back_and_closes_on_failure() -> None:
    connection = FakeConnection([FakeResult()])
    repository = PostgresLoginRepository(FakeEngine(connection))

    async def exercise() -> None:
        with pytest.raises(RuntimeError):
            async with repository:
                raise RuntimeError("forced failure")

    asyncio.run(exercise())

    assert connection.transaction.committed is False
    assert connection.transaction.rolled_back is True
    assert connection.closed is True


def test_repository_requires_verified_user_context_before_session_write() -> None:
    connection = FakeConnection([FakeResult()])
    repository = PostgresLoginRepository(FakeEngine(connection))
    creation = SessionCreation(
        session_id=SESSION_ID,
        user_id=USER_ID,
        organization_id=ORG_ID,
        session_token_hash=b"a" * 32,
        csrf_token_hash=b"b" * 32,
        expires_at=NOW + timedelta(hours=1),
        last_seen_at=NOW,
        user_agent=None,
        ip_address=None,
    )

    async def exercise() -> None:
        async with repository:
            with pytest.raises(RuntimeError):
                await repository.replace_for_login(
                    creation,
                    previous_token_hash=None,
                )

    asyncio.run(exercise())


def test_repository_loads_session_by_token_then_renews_verified_row() -> None:
    connection = FakeConnection(
        [
            FakeResult(),
            FakeResult(),
            FakeResult(
                one={
                    "session_id": SESSION_ID,
                    "organization_id": ORG_ID,
                    "user_id": USER_ID,
                    "csrf_token_hash": b"b" * 32,
                    "expires_at": NOW + timedelta(minutes=30),
                    "last_seen_at": NOW - timedelta(minutes=30),
                    "is_revoked": False,
                    "created_at": NOW - timedelta(days=1),
                }
            ),
            FakeResult(),
            FakeResult(rowcount=1),
            FakeResult(rowcount=1),
            FakeResult(),
            FakeResult(),
            FakeResult(scalar_values=["devices:read", "tickets:read"]),
        ]
    )
    repository = PostgresLoginRepository(FakeEngine(connection))

    async def exercise() -> None:
        async with repository:
            record = await repository.find_by_token_hash(b"a" * 32)
            assert record is not None
            await repository.touch_session(
                session_id=record.session_id,
                user_id=record.user_id,
                last_seen_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )
            await repository.revoke_current_session(
                session_id=record.session_id,
                user_id=record.user_id,
            )
            permissions = await repository.load_permissions(
                user_id=record.user_id,
                organization_id=ORG_ID,
            )
            assert permissions == frozenset({"devices:read", "tickets:read"})

    asyncio.run(exercise())

    calls = connection.calls
    assert calls[1][1] == {"session_token_hash": (b"a" * 32).hex()}
    assert calls[3][1] == {"user_id": str(USER_ID)}
    assert calls[4][1] == {
        "session_id": SESSION_ID,
        "user_id": USER_ID,
        "last_seen_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
    }
    assert calls[5][1] == {
        "session_id": SESSION_ID,
        "user_id": USER_ID,
    }
    assert calls[7][1] == {"org_id": str(ORG_ID)}
    assert calls[8][1] == {
        "organization_id": ORG_ID,
        "user_id": USER_ID,
    }


def test_repository_updates_only_credential_lock_fields_with_bound_email() -> None:
    connection = FakeConnection([FakeResult(), FakeResult(), FakeResult()])
    repository = PostgresLoginRepository(FakeEngine(connection))

    async def exercise() -> None:
        async with repository:
            await repository.record_credential_failure(
                "user@example.test",
                now=NOW,
            )
            await repository.clear_credential_failures("user@example.test")

    asyncio.run(exercise())

    sql = "\n".join(statement for statement, _ in connection.calls)
    assert "user@example.test" not in sql
    assert connection.calls[1][1] == {
        "email": "user@example.test",
        "now": NOW,
    }
    assert connection.calls[2][1] == {"email": "user@example.test"}
    assert "password_hash" not in sql


def test_repository_consumes_reset_atomically_with_row_lock_and_revocations() -> None:
    token_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    connection = FakeConnection(
        [
            FakeResult(),
            FakeResult(
                one={
                    "token_id": token_id,
                    "user_id": USER_ID,
                    "token_hash": b"h" * 32,
                    "expires_at": NOW + timedelta(minutes=15),
                    "used_at": None,
                    "is_revoked": False,
                }
            ),
            FakeResult(rowcount=1),
            FakeResult(),
            FakeResult(),
            FakeResult(),
        ]
    )
    repository = PostgresLoginRepository(FakeEngine(connection))

    async def exercise() -> None:
        async with repository:
            record = await repository.lock_password_reset_token(token_id)
            assert isinstance(record, PasswordResetRecord)
            await repository.consume_password_reset(
                token_id=token_id,
                user_id=USER_ID,
                password_hash="$argon2id$replacement",
                used_at=NOW,
            )

    asyncio.run(exercise())

    sql = "\n".join(statement for statement, _ in connection.calls)
    assert "FOR UPDATE" in sql
    assert "UPDATE public.users" in sql
    assert "UPDATE public.password_reset_tokens" in sql
    assert "UPDATE public.user_sessions" in sql
    assert "$argon2id$replacement" not in sql


def test_repository_replaces_pending_reset_token_for_verified_active_user() -> None:
    token_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    connection = FakeConnection(
        [
            FakeResult(),
            FakeResult(one={"user_id": USER_ID}),
            FakeResult(),
            FakeResult(),
        ]
    )
    repository = PostgresLoginRepository(FakeEngine(connection))

    async def exercise() -> None:
        async with repository:
            user_id = await repository.find_active_reset_user_id(
                "user@example.test"
            )
            assert user_id == USER_ID
            await repository.replace_password_reset_token(
                token_id=token_id,
                user_id=USER_ID,
                token_hash=b"h" * 32,
                created_at=NOW,
                expires_at=NOW + timedelta(minutes=15),
            )

    asyncio.run(exercise())

    sql = "\n".join(statement for statement, _ in connection.calls)
    assert "user@example.test" not in sql
    assert "UPDATE public.password_reset_tokens" in sql
    assert "INSERT INTO public.password_reset_tokens" in sql
    assert connection.calls[1][1] == {"email": "user@example.test"}
    assert connection.calls[3][1] == {
        "token_id": token_id,
        "user_id": USER_ID,
        "token_hash": b"h" * 32,
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
    }
