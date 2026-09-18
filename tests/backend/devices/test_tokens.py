import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import hmac
from uuid import UUID

import pytest

from backend.app.devices.service import (
    AgentIdentity,
    AgentTokenApplication,
    AgentTokenRejected,
    DeviceToken,
    DeviceTokenRecord,
    hash_device_secret,
    parse_device_token,
)


PEPPER = b"p" * 32
ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
TOKEN_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOW = datetime(2026, 8, 24, tzinfo=UTC)


def test_device_token_contains_32_random_bytes_and_hides_secret() -> None:
    token = DeviceToken.generate(PEPPER)
    token_id, secret = parse_device_token(token.value)
    padding = "=" * (-len(secret) % 4)

    assert token_id == token.token_id
    assert len(base64.urlsafe_b64decode(secret + padding)) == 32
    assert token.secret_hash == hash_device_secret(secret, PEPPER)
    assert secret not in repr(token)


@pytest.mark.parametrize(
    "value",
    ["", "not-a-token", f"{TOKEN_ID}.", f"{TOKEN_ID}.secret.extra"],
)
def test_device_token_parser_rejects_ambiguous_values(value: str) -> None:
    with pytest.raises(ValueError, match="invalid device token"):
        parse_device_token(value)


class Repository:
    def __init__(self, record: DeviceTokenRecord | None) -> None:
        self.record = record
        self.activated: DeviceTokenRecord | None = None

    async def find_token(self, token_id: UUID) -> DeviceTokenRecord | None:
        assert token_id == TOKEN_ID
        return self.record

    async def activate_identity(
        self, record: DeviceTokenRecord, *, used_at: datetime
    ) -> bool:
        assert used_at == NOW
        self.activated = record
        return True


def repository_factory(repository: Repository):
    @asynccontextmanager
    async def factory():
        yield repository

    return factory


def record_for(secret: str, **changes: object) -> DeviceTokenRecord:
    values = {
        "token_id": TOKEN_ID,
        "organization_id": ORG_ID,
        "device_id": DEVICE_ID,
        "secret_hash": hash_device_secret(secret, PEPPER),
        "expires_at": NOW + timedelta(days=1),
        "is_revoked": False,
    }
    values.update(changes)
    return DeviceTokenRecord(**values)


def test_agent_authentication_uses_constant_time_comparison(monkeypatch) -> None:
    secret = "v" * 43
    repository = Repository(record_for(secret))
    calls: list[tuple[bytes, bytes]] = []
    original = hmac.compare_digest

    def compare_digest(left: bytes, right: bytes) -> bool:
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(hmac, "compare_digest", compare_digest)
    application = AgentTokenApplication(
        repository_factory(repository), pepper=PEPPER, clock=lambda: NOW
    )

    identity = asyncio.run(application.authenticate(f"{TOKEN_ID}.{secret}"))

    assert identity == AgentIdentity(
        organization_id=ORG_ID,
        device_id=DEVICE_ID,
        token_id=TOKEN_ID,
    )
    assert repository.activated is repository.record
    assert len(calls) == 1


@pytest.mark.parametrize(
    "record,token",
    [
        (None, f"{TOKEN_ID}.{'u' * 43}"),
        (record_for("r" * 43), f"{TOKEN_ID}.{'w' * 43}"),
        (record_for("r" * 43, is_revoked=True), f"{TOKEN_ID}.{'r' * 43}"),
        (
            record_for("r" * 43, expires_at=NOW - timedelta(seconds=1)),
            f"{TOKEN_ID}.{'r' * 43}",
        ),
    ],
)
def test_agent_authentication_rejects_invalid_lifecycle_uniformly(
    record: DeviceTokenRecord | None, token: str
) -> None:
    repository = Repository(record)
    application = AgentTokenApplication(
        repository_factory(repository), pepper=PEPPER, clock=lambda: NOW
    )

    with pytest.raises(AgentTokenRejected, match="Autenticación de agente requerida"):
        asyncio.run(application.authenticate(token))

    assert repository.activated is None
