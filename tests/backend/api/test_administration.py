from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.administration.service import AuditLogSummary, RoleSummary
from backend.app.api.administration import administration_router
from backend.app.api.errors import install_error_handlers
from backend.app.auth.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from backend.app.auth.session import SessionIdentity
from backend.app.auth.session_tokens import hash_token


USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ORG_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ROLE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
SESSION_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)


class Sessions:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.permissions = permissions

    async def authenticate(
        self, _token: str, *, require_organization: bool = True
    ) -> SessionIdentity:
        assert require_organization
        return SessionIdentity(
            session_id=SESSION_ID,
            organization_id=ORG_ID,
            user_id=USER_ID,
            csrf_token_hash=hash_token("csrf-token"),
            permissions=self.permissions,
        )


class RateLimiter:
    async def allow(self, _session_id: UUID) -> None:
        return None


class Administration:
    def __init__(self) -> None:
        self.created: dict[str, object] | None = None
        self.assigned: dict[str, object] | None = None

    async def list_roles(self, organization_id: UUID) -> tuple[RoleSummary, ...]:
        assert organization_id == ORG_ID
        return (RoleSummary(ROLE_ID, "HELPDESK", "Help desk", False, ("tickets:read",)),)

    async def create_role(self, **values: object) -> RoleSummary:
        self.created = values
        return RoleSummary(ROLE_ID, str(values["name"]), str(values["description"]), False, tuple(values["permissions"]))

    async def assign_role(self, **values: object) -> None:
        self.assigned = values

    async def list_audit_logs(self, **_values: object) -> tuple[AuditLogSummary, ...]:
        return (
            AuditLogSummary(
                id=ROLE_ID,
                actor_id=USER_ID,
                actor_type="USER",
                action="RBAC.ROLE_CREATED",
                resource_type="ROLE",
                resource_id=ROLE_ID,
                status="SUCCESS",
                details={"name": "HELPDESK"},
                created_at=NOW,
            ),
        )


def _client(permissions: frozenset[str]) -> tuple[TestClient, Administration]:
    administration = Administration()
    app = FastAPI()
    app.state.session_application = Sessions(permissions)
    app.state.session_request_rate_limiter = RateLimiter()
    app.state.administration = administration
    install_error_handlers(app)
    app.include_router(administration_router, prefix="/api/v1")
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, "session")
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-token")
    return client, administration


def test_role_list_and_audit_output_are_tenant_derived_and_trimmed() -> None:
    client, _ = _client(frozenset({"roles:manage_custom", "audit:read_logs"}))

    roles = client.get("/api/v1/roles")
    audits = client.get("/api/v1/audit-logs")

    assert roles.status_code == 200
    assert roles.json()["items"][0]["permissions"] == ["tickets:read"]
    assert audits.status_code == 200
    assert audits.json()["items"][0]["action"] == "RBAC.ROLE_CREATED"
    assert "ip_address" not in audits.text


def test_role_creation_requires_permission_csrf_and_rejects_protected_fields() -> None:
    client, administration = _client(frozenset({"roles:manage_custom"}))
    payload = {
        "name": "HELPDESK",
        "description": "Help desk",
        "permissions": ["tickets:read"],
    }

    no_csrf = client.post("/api/v1/roles", json=payload)
    client.headers["X-CSRF-Token"] = "csrf-token"
    injected = client.post(
        "/api/v1/roles", json={**payload, "organization_id": str(ORG_ID)}
    )
    created = client.post("/api/v1/roles", json=payload)

    assert no_csrf.status_code == 403
    assert injected.status_code == 422
    assert created.status_code == 201
    assert administration.created is not None
    assert administration.created["organization_id"] == ORG_ID
    assert administration.created["actor_id"] == USER_ID


def test_role_assignment_derives_actor_and_rejects_without_permission() -> None:
    client, administration = _client(frozenset({"roles:manage_custom"}))
    client.headers["X-CSRF-Token"] = "csrf-token"

    response = client.post(
        f"/api/v1/roles/{ROLE_ID}/assignments",
        json={"user_id": str(USER_ID)},
    )

    assert response.status_code == 204
    assert administration.assigned is not None
    assert administration.assigned["organization_id"] == ORG_ID
    assert administration.assigned["actor_id"] == USER_ID

    denied, _ = _client(frozenset())
    denied.headers["X-CSRF-Token"] = "csrf-token"
    assert denied.post(
        f"/api/v1/roles/{ROLE_ID}/assignments",
        json={"user_id": str(USER_ID)},
    ).status_code == 403


def test_list_permissions_returns_canonical_permissions() -> None:
    client, _ = _client(frozenset({"roles:manage_custom"}))
    response = client.get("/api/v1/permissions")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) > 0
    codes = {p["code"] for p in data["items"]}
    assert "devices:read" in codes
    assert "tickets:create" in codes
    assert "roles:manage_custom" in codes
