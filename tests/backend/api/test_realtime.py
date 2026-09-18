from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.api.realtime import realtime_router
from backend.app.auth.cookies import SESSION_COOKIE_NAME
from backend.app.auth.session import SessionIdentity
from backend.app.auth.session_tokens import hash_token


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class Sessions:
    async def authenticate(
        self, token: str, *, require_organization: bool = True
    ) -> SessionIdentity:
        assert token == "valid-session"
        assert require_organization
        return SessionIdentity(
            session_id=UUID(int=1),
            organization_id=ORG_ID,
            user_id=UUID(int=2),
            csrf_token_hash=hash_token("csrf"),
        )


class Hub:
    def __init__(self) -> None:
        self.organization_id: UUID | None = None

    def accepts_origin(self, origin: str | None) -> bool:
        return origin == "https://app.example.test"

    async def serve(self, websocket: object, organization_id: UUID) -> None:
        self.organization_id = organization_id
        await websocket.send_json({"type": "ready"})  # type: ignore[attr-defined]
        await websocket.receive_text()  # type: ignore[attr-defined]


def _client() -> tuple[TestClient, Hub]:
    app = FastAPI()
    hub = Hub()
    app.state.session_application = Sessions()
    app.state.realtime_hub = hub
    app.include_router(realtime_router, prefix="/api/v1")
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, "valid-session")
    return client, hub


def test_websocket_uses_authenticated_tenant_only() -> None:
    client, hub = _client()

    with client.websocket_connect(
        "/api/v1/ws/telemetry?organization_id=ffffffff-ffff-4fff-8fff-ffffffffffff",
        headers={"Origin": "https://app.example.test"},
    ) as websocket:
        assert websocket.receive_json() == {"type": "ready"}
        websocket.send_text("close")

    assert hub.organization_id == ORG_ID


def test_websocket_rejects_missing_or_untrusted_origin() -> None:
    client, _ = _client()

    with pytest.raises(WebSocketDisconnect) as missing:
        with client.websocket_connect("/api/v1/ws/telemetry"):
            pass
    with pytest.raises(WebSocketDisconnect) as untrusted:
        with client.websocket_connect(
            "/api/v1/ws/telemetry",
            headers={"Origin": "https://evil.example"},
        ):
            pass

    assert missing.value.code == 1008
    assert untrusted.value.code == 1008
