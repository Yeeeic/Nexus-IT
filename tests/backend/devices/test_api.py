from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.devices import devices_router
from backend.app.api.errors import install_error_handlers
from backend.app.auth.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from backend.app.auth.session import SessionIdentity
from backend.app.auth.session_tokens import hash_token
from backend.app.devices.service import (
    AgentIdentity,
    DeviceEnrollmentResult,
    DeviceRecord,
    InventorySnapshot,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_ORG_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
DEVICE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
TOKEN_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
SESSION_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
NOW = datetime(2026, 8, 24, tzinfo=UTC)


class SessionApplication:
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


class AgentApplication:
    async def authenticate(self, token: str) -> AgentIdentity:
        assert token == "agent-token"
        return AgentIdentity(ORG_ID, DEVICE_ID, TOKEN_ID)


class AgentRateLimiter:
    async def preflight(self, _token: str, _ip_address: str) -> None:
        return None


class SessionRateLimiter:
    async def allow(self, _session_id: UUID) -> None:
        return None


class DeviceService:
    def __init__(self) -> None:
        self.enrollment_call = None
        self.list_call = None
        self.inventory_call = None

    async def enroll(self, organization_id, actor_id, command, audit):
        self.enrollment_call = (organization_id, actor_id, command, audit)
        return DeviceEnrollmentResult(
            device=DeviceRecord(
                organization_id=ORG_ID,
                id=DEVICE_ID,
                hostname=command.hostname,
                display_name=command.display_name,
                is_active=True,
                last_seen_at=None,
                created_at=NOW,
                updated_at=NOW,
            ),
            token_id=TOKEN_ID,
            token=f"{TOKEN_ID}.one-time-secret",
            token_expires_at=command.token_expires_at,
        )

    async def list_devices(
        self, organization_id, *, actor_id, assigned_only, limit, after_id
    ):
        self.list_call = (
            organization_id,
            actor_id,
            assigned_only,
            limit,
            after_id,
        )
        return (
            (
                DeviceRecord(
                    ORG_ID,
                    DEVICE_ID,
                    "host-1",
                    "Desk",
                    True,
                    None,
                    NOW,
                    NOW,
                ),
            ),
            None,
        )

    async def write_inventory(self, identity, snapshot):
        self.inventory_call = (identity, snapshot)
        return InventorySnapshot(
            organization_id=identity.organization_id,
            device_id=identity.device_id,
            hardware=snapshot.hardware,
            software_packages=snapshot.software_packages,
            patches=snapshot.patches,
            services=snapshot.services,
            collected_at=snapshot.collected_at,
            updated_at=NOW,
        )

    async def assign_device(
        self, organization_id, device_id, user_id, actor_id, audit
    ):
        self.assignment_call = (
            organization_id,
            device_id,
            user_id,
            actor_id,
            audit,
        )


def make_client(*permissions: str) -> tuple[TestClient, DeviceService]:
    service = DeviceService()
    app = FastAPI()
    app.state.session_application = SessionApplication(frozenset(permissions))
    app.state.session_request_rate_limiter = SessionRateLimiter()
    app.state.agent_token_application = AgentApplication()
    app.state.agent_request_rate_limiter = AgentRateLimiter()
    app.state.device_service = service
    install_error_handlers(app)
    app.include_router(devices_router, prefix="/api/v1")
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-token")
    return client, service


def test_enrollment_derives_tenant_and_exposes_secret_once() -> None:
    client, service = make_client("devices:enroll")

    response = client.post(
        "/api/v1/devices",
        headers={"X-CSRF-Token": "csrf-token"},
        json={"hostname": "host-1", "display_name": "Desk"},
    )

    assert response.status_code == 201
    assert response.json()["token"] == f"{TOKEN_ID}.one-time-secret"
    assert response.headers["cache-control"] == "no-store"
    assert service.enrollment_call[0:2] == (ORG_ID, USER_ID)


def test_enrollment_rejects_protected_tenant_field() -> None:
    client, service = make_client("devices:enroll")

    response = client.post(
        "/api/v1/devices",
        headers={"X-CSRF-Token": "csrf-token"},
        json={"hostname": "host-1", "organization_id": str(OTHER_ORG_ID)},
    )

    assert response.status_code == 422
    assert service.enrollment_call is None


def test_enrollment_requires_permission_and_csrf() -> None:
    client, service = make_client()

    forbidden = client.post(
        "/api/v1/devices",
        headers={"X-CSRF-Token": "csrf-token"},
        json={"hostname": "host-1"},
    )
    no_csrf_client, _ = make_client("devices:enroll")
    no_csrf = no_csrf_client.post(
        "/api/v1/devices", json={"hostname": "host-1"}
    )

    assert forbidden.status_code == 403
    assert no_csrf.status_code == 403
    assert service.enrollment_call is None


def test_device_list_uses_session_tenant_and_never_returns_token() -> None:
    client, service = make_client("devices:read")

    response = client.get(
        "/api/v1/devices",
        params={"limit": 25, "organization_id": str(OTHER_ORG_ID)},
    )

    assert response.status_code == 200
    assert service.list_call == (ORG_ID, USER_ID, True, 25, None)
    assert "token" not in response.text.lower()


def test_device_assignment_requires_explicit_permission_and_tenant_context() -> None:
    client, service = make_client("devices:assign")

    response = client.post(
        f"/api/v1/devices/{DEVICE_ID}/assignments",
        headers={"X-CSRF-Token": "csrf-token"},
        json={"user_id": str(USER_ID)},
    )

    assert response.status_code == 204
    assert service.assignment_call[:4] == (
        ORG_ID,
        DEVICE_ID,
        USER_ID,
        USER_ID,
    )


def test_agent_inventory_derives_identity_and_rejects_cross_device_path() -> None:
    client, service = make_client()
    payload = {
        "hardware": {"cpu_model": "CPU", "memory_bytes": 1024},
        "software_packages": [],
        "patches": [],
        "services": [],
        "collected_at": NOW.isoformat(),
    }

    accepted = client.put(
        f"/api/v1/devices/{DEVICE_ID}/inventory",
        headers={"Authorization": "Bearer agent-token"},
        json=payload,
    )
    rejected = client.put(
        f"/api/v1/devices/{UUID(int=1)}/inventory",
        headers={"Authorization": "Bearer agent-token"},
        json=payload,
    )

    assert accepted.status_code == 200
    assert service.inventory_call[0] == AgentIdentity(ORG_ID, DEVICE_ID, TOKEN_ID)
    assert rejected.status_code == 404


def test_agent_inventory_rejects_extra_nested_fields() -> None:
    client, service = make_client()

    response = client.put(
        f"/api/v1/devices/{DEVICE_ID}/inventory",
        headers={"Authorization": "Bearer agent-token"},
        json={
            "hardware": {
                "cpu_model": "CPU",
                "memory_bytes": 1024,
                "organization_id": str(OTHER_ORG_ID),
            },
            "collected_at": NOW.isoformat(),
        },
    )

    assert response.status_code == 422
    assert service.inventory_call is None
