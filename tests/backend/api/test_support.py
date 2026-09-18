from datetime import datetime, timezone
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import install_error_handlers
from backend.app.api.support import install_support_error_handlers, support_router
from backend.app.auth.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from backend.app.auth.session import SessionIdentity
from backend.app.auth.session_tokens import hash_token
from backend.app.devices.service import AgentIdentity
from backend.app.support.schemas import ActionRequest
from backend.app.support.service import (
    ActionCommand,
    ActionAcknowledgement,
    ActionResult,
    AttachmentDownload,
    AttachmentRecord,
    RequestTrace,
    TicketRecord,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
DEVICE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ACTION_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
ATTACHMENT_ID = UUID("12121212-1212-4121-8121-121212121212")
NONCE = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
SESSION_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
NOW = datetime(2026, 8, 24, 18, 30, tzinfo=timezone.utc)


class Sessions:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.permissions = permissions

    async def authenticate(
        self, _token: str, *, require_organization: bool = True
    ) -> SessionIdentity:
        return SessionIdentity(
            session_id=SESSION_ID,
            organization_id=ORG_ID,
            user_id=USER_ID,
            csrf_token_hash=hash_token("csrf"),
            permissions=self.permissions,
        )


class Support:
    def __init__(self) -> None:
        self.action_call: tuple[UUID, UUID, UUID, ActionRequest, RequestTrace] | None = None

    async def request_action(
        self,
        *,
        organization_id: UUID,
        device_id: UUID,
        actor_id: UUID,
        request: ActionRequest,
        trace: RequestTrace,
    ) -> ActionCommand:
        self.action_call = (organization_id, device_id, actor_id, request, trace)
        return ActionCommand(
            organization_id=organization_id,
            id=ACTION_ID,
            device_id=device_id,
            action_name=request.action_name,
            requested_by=actor_id,
            nonce=NONCE,
            key_version=1,
            issued_at=NOW,
            expires_at=NOW.replace(minute=35),
            signature="signed",
            parameters=request.parameters,
            parameters_canonical=request.canonical_parameters,
            status="DISPATCHED",
            trace=trace,
        )

    async def record_action_result(self, **values: object) -> ActionResult:
        assert values["organization_id"] == ORG_ID
        assert values["device_id"] == DEVICE_ID
        assert values["token_id"] == NONCE
        return ActionResult(status="COMPLETED", is_replay=False)

    async def upload_attachment(self, **values: object) -> AttachmentRecord:
        assert values["organization_id"] == ORG_ID
        assert values["original_name"] == "screen.png"
        return AttachmentRecord(
            id=ATTACHMENT_ID,
            ticket_id=ACTION_ID,
            original_name="screen.png",
            stored_filename="hidden.png",
            mime_type="image/png",
            file_size=12,
            storage_path="hidden/path",
            uploaded_at=NOW,
        )

    async def download_attachment(self, **values: object) -> AttachmentDownload:
        assert values["organization_id"] == ORG_ID
        return AttachmentDownload(
            original_name='screen.png',
            mime_type="image/png",
            content=b"png-content",
        )

    async def get_ticket(self, **values: object) -> TicketRecord:
        assert values["organization_id"] == ORG_ID
        assert values["ticket_id"] == ACTION_ID
        return TicketRecord(
            id=ACTION_ID,
            device_id=DEVICE_ID,
            alert_id=None,
            created_by=USER_ID,
            assigned_to=None,
            ticket_number="NEX-1234",
            title="Database slow",
            description="High latency on query",
            status="OPEN",
            priority="HIGH",
            resolved_at=None,
            created_at=NOW,
            updated_at=NOW,
        )

    async def poll_actions(self, **values: object) -> tuple[ActionCommand, ...]:
        assert values["organization_id"] == ORG_ID
        assert values["device_id"] == DEVICE_ID
        return (
            ActionCommand(
                organization_id=ORG_ID,
                id=ACTION_ID,
                device_id=DEVICE_ID,
                action_name="flush_dns",
                requested_by=USER_ID,
                nonce=NONCE,
                key_version=1,
                issued_at=NOW,
                expires_at=NOW.replace(minute=35),
                signature="signed",
                parameters={},
                parameters_canonical="{}",
                status="DISPATCHED",
                trace=RequestTrace(None, None),
            ),
        )

    async def acknowledge_action(self, **values: object) -> ActionAcknowledgement:
        assert values["token_id"] == NONCE
        return ActionAcknowledgement(status="ACCEPTED", is_replay=False)


class AgentTokens:
    async def authenticate(self, token: str) -> AgentIdentity:
        assert token == "agent-token"
        return AgentIdentity(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            token_id=NONCE,
        )


class AgentRateLimiter:
    async def preflight(self, _token: str, _ip_address: str) -> None:
        return None


class SessionRateLimiter:
    async def allow(self, _session_id: UUID) -> None:
        return None


def make_client(permissions: frozenset[str]) -> tuple[TestClient, Support]:
    support = Support()
    app = FastAPI()
    app.state.session_application = Sessions(permissions)
    app.state.support_application = support
    app.state.agent_token_application = AgentTokens()
    app.state.agent_request_rate_limiter = AgentRateLimiter()
    app.state.session_request_rate_limiter = SessionRateLimiter()
    install_error_handlers(app)
    install_support_error_handlers(app)
    app.include_router(support_router, prefix="/api/v1")
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, "session")
    client.cookies.set(CSRF_COOKIE_NAME, "csrf")
    return client, support


def test_remote_action_requires_csrf_permission_and_derives_tenant() -> None:
    client, support = make_client(frozenset({"actions:request_exec"}))

    denied = client.post(
        f"/api/v1/devices/{DEVICE_ID}/actions",
        json={"action_name": "flush_dns", "parameters": {}},
    )
    response = client.post(
        f"/api/v1/devices/{DEVICE_ID}/actions",
        headers={"X-CSRF-Token": "csrf"},
        json={"action_name": "flush_dns", "parameters": {}},
    )

    assert denied.status_code == 403
    assert response.status_code == 201
    assert response.json()["organization_id"] == str(ORG_ID)
    assert support.action_call is not None
    assert support.action_call[:3] == (ORG_ID, DEVICE_ID, USER_ID)


def test_remote_action_rejects_unknown_fields_before_service() -> None:
    client, support = make_client(frozenset({"actions:request_exec"}))

    response = client.post(
        f"/api/v1/devices/{DEVICE_ID}/actions",
        headers={"X-CSRF-Token": "csrf"},
        json={
            "action_name": "flush_dns",
            "parameters": {},
            "command": "whoami",
        },
    )

    assert response.status_code == 422
    assert support.action_call is None


def test_action_result_requires_matching_authenticated_device() -> None:
    client, _support = make_client(frozenset())
    other_device = UUID("11111111-1111-4111-8111-111111111111")
    body = {"status": "SUCCEEDED", "exit_code": 0, "output_summary": "ok"}

    hidden = client.post(
        f"/api/v1/devices/{other_device}/actions/{ACTION_ID}/result",
        headers={"Authorization": "Bearer agent-token"},
        json=body,
    )
    response = client.post(
        f"/api/v1/devices/{DEVICE_ID}/actions/{ACTION_ID}/result",
        headers={"Authorization": "Bearer agent-token"},
        json=body,
    )

    assert hidden.status_code == 404
    assert response.status_code == 200
    assert response.json() == {"status": "COMPLETED", "is_replay": False}


def test_attachment_upload_hides_storage_and_download_forces_safe_headers() -> None:
    client, _support = make_client(
        frozenset({"tickets:create", "tickets:read", "tickets:internal_notes"})
    )

    uploaded = client.post(
        f"/api/v1/tickets/{ACTION_ID}/attachments",
        headers={"X-CSRF-Token": "csrf", "X-File-Name": "screen.png"},
        content=b"\x89PNG\r\n\x1a\nmore",
    )
    downloaded = client.get(
        f"/api/v1/tickets/{ACTION_ID}/attachments/{ATTACHMENT_ID}"
    )

    assert uploaded.status_code == 201
    assert "storage" not in uploaded.text.lower()
    assert downloaded.status_code == 200
    assert downloaded.content == b"png-content"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["content-disposition"].startswith("attachment;")


def test_agent_can_poll_and_ack_only_its_own_device_actions() -> None:
    client, _support = make_client(frozenset())
    headers = {"Authorization": "Bearer agent-token"}

    polled = client.get(
        f"/api/v1/devices/{DEVICE_ID}/actions", headers=headers
    )
    acknowledged = client.post(
        f"/api/v1/devices/{DEVICE_ID}/actions/{ACTION_ID}/ack",
        headers=headers,
    )

    assert polled.status_code == 200
    assert polled.json()["items"][0]["action_name"] == "flush_dns"
    assert acknowledged.status_code == 200
    assert acknowledged.json() == {"status": "ACCEPTED", "is_replay": False}


def test_get_single_ticket_returns_ticket_details() -> None:
    client, _support = make_client(frozenset({"tickets:read"}))
    response = client.get(f"/api/v1/tickets/{ACTION_ID}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(ACTION_ID)
    assert data["ticket_number"] == "NEX-1234"
    assert data["title"] == "Database slow"


def test_operator_can_poll_device_actions_with_session_cookie() -> None:
    client, _support = make_client(frozenset({"devices:read"}))
    response = client.get(f"/api/v1/devices/{DEVICE_ID}/actions")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["action_name"] == "flush_dns"
