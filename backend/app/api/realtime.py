"""Versioned, authenticated tenant WebSocket endpoint."""

from typing import Protocol, cast
from uuid import UUID

from fastapi import APIRouter, WebSocket

from backend.app.auth.cookies import SESSION_COOKIE_NAME
from backend.app.auth.session import SessionIdentity
from backend.app.realtime.hub import RedisRealtimeHub


realtime_router = APIRouter(tags=["realtime"])


class SessionApplication(Protocol):
    async def authenticate(
        self,
        session_token: str,
        *,
        require_organization: bool = True,
    ) -> SessionIdentity: ...


@realtime_router.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket) -> None:
    hub = cast(RedisRealtimeHub | None, getattr(websocket.app.state, "realtime_hub", None))
    sessions = cast(
        SessionApplication | None,
        getattr(websocket.app.state, "session_application", None),
    )
    origin = websocket.headers.get("origin")
    if hub is None or sessions is None or not hub.accepts_origin(origin):
        await websocket.close(code=1008)
        return
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        await websocket.close(code=1008)
        return
    try:
        identity = await sessions.authenticate(token, require_organization=True)
    except Exception:
        await websocket.close(code=1008)
        return
    organization_id: UUID | None = identity.organization_id
    if organization_id is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await hub.serve(websocket, organization_id)
