from uuid import UUID

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    require_csrf,
    require_permission,
    require_session,
)
from backend.app.api.errors import install_error_handlers
from backend.app.auth.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from backend.app.auth.session import SessionIdentity, SessionRejected
from backend.app.auth.session_tokens import hash_token


SESSION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ORG_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
SESSION_TOKEN = "valid-session-token"
CSRF_TOKEN = "valid-csrf-token"
IDENTITY = SessionIdentity(
    session_id=SESSION_ID,
    organization_id=ORG_ID,
    user_id=USER_ID,
    csrf_token_hash=hash_token(CSRF_TOKEN),
    permissions=frozenset({"devices:read"}),
)


class SessionApplication:
    def __init__(self, rejected: bool = False) -> None:
        self.rejected = rejected
        self.token: str | None = None

    async def authenticate(
        self,
        session_token: str,
        *,
        require_organization: bool = True,
    ) -> SessionIdentity:
        self.token = session_token
        if self.rejected:
            raise SessionRejected
        assert require_organization is True
        return IDENTITY


class RateLimiter:
    async def allow(self, _session_id: UUID) -> None:
        return None


def _client(application: SessionApplication) -> TestClient:
    app = FastAPI()
    app.state.session_application = application
    app.state.session_request_rate_limiter = RateLimiter()
    install_error_handlers(app)

    @app.get("/private")
    async def private_get(
        identity: SessionIdentity = Depends(require_session),
    ) -> dict[str, str]:
        return {"organization_id": str(identity.organization_id)}

    @app.post("/private")
    async def private_post(
        identity: SessionIdentity = Depends(require_csrf),
    ) -> dict[str, str]:
        return {"organization_id": str(identity.organization_id)}

    @app.get("/devices")
    async def devices(
        _identity: SessionIdentity = Depends(
            require_permission("devices:read")
        ),
    ) -> dict[str, str]:
        return {"status": "allowed"}

    @app.get("/admin")
    async def admin(
        _identity: SessionIdentity = Depends(
            require_permission("users:manage")
        ),
    ) -> dict[str, str]:
        return {"status": "allowed"}

    return TestClient(app, base_url="https://testserver")


def test_private_route_requires_valid_session_cookie() -> None:
    application = SessionApplication()
    client = _client(application)

    missing = client.get("/private")
    assert missing.status_code == 401

    client.cookies.set(SESSION_COOKIE_NAME, SESSION_TOKEN)
    accepted = client.get("/private")

    assert accepted.status_code == 200
    assert accepted.json() == {"organization_id": str(ORG_ID)}
    assert application.token == SESSION_TOKEN
    refreshed = accepted.headers.get_list("set-cookie")
    assert any("__Host-nexus_session=" in cookie for cookie in refreshed)
    assert all("Max-Age=3600" in cookie for cookie in refreshed)


def test_private_mutation_requires_double_submit_csrf() -> None:
    client = _client(SessionApplication())
    client.cookies.set(SESSION_COOKIE_NAME, SESSION_TOKEN)

    assert client.post("/private").status_code == 403

    client.cookies.set(CSRF_COOKIE_NAME, CSRF_TOKEN)
    assert (
        client.post(
            "/private",
            headers={"X-CSRF-Token": "wrong-token"},
        ).status_code
        == 403
    )

    accepted = client.post(
        "/private",
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )
    assert accepted.status_code == 200


def test_rejected_or_revoked_session_returns_safe_401() -> None:
    client = _client(SessionApplication(rejected=True))
    client.cookies.set(SESSION_COOKIE_NAME, "revoked-session-token")

    response = client.get("/private")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert "revoked-session-token" not in response.text


def test_permission_dependency_enforces_rbac_matrix() -> None:
    client = _client(SessionApplication())
    client.cookies.set(SESSION_COOKIE_NAME, SESSION_TOKEN)

    assert client.get("/devices").status_code == 200
    denied = client.get("/admin")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"
