from datetime import datetime, timezone
from dataclasses import dataclass
import json
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import install_error_handlers
from backend.app.api.metrics import metrics_router
from backend.app.auth.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from backend.app.auth.session import SessionIdentity
from backend.app.auth.session_tokens import hash_token
from backend.app.metrics.schemas import MetricBatchInput
from backend.app.metrics.service import (
    BatchDiagnostics,
    BatchReceipt,
    BatchStatusRecord,
    TelemetrySample,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEVICE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
BATCH_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
TOKEN_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


class AgentAuthenticator:
    async def authenticate(self, token: str):
        assert token == "agent-token"
        return AgentIdentity(
            organization_id=ORG_ID,
            device_id=DEVICE_ID,
            token_id=TOKEN_ID,
        )


@dataclass(frozen=True)
class AgentIdentity:
    organization_id: UUID
    device_id: UUID
    token_id: UUID


class RateLimiter:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    async def allow(self, organization_id: UUID, token_id: UUID) -> None:
        self.calls.append((organization_id, token_id))


class SessionRateLimiter:
    async def allow(self, _session_id: UUID) -> None:
        return None


class SessionApplication:
    def __init__(self, permissions: set[str] | None = None) -> None:
        self.permissions = permissions or {
            "metrics:read_telemetry",
            "metrics:retry_dlq",
            "metrics:export_dlq_diagnostics",
            "metrics:decide_dlq",
        }

    async def authenticate(
        self, _token: str, *, require_organization: bool = True
    ) -> SessionIdentity:
        assert require_organization
        return SessionIdentity(
            session_id=UUID(int=3),
            organization_id=ORG_ID,
            user_id=UUID(int=4),
            csrf_token_hash=hash_token("csrf"),
            permissions=frozenset(self.permissions),
        )


class Application:
    def __init__(self) -> None:
        self.ingest_call: tuple[object, ...] | None = None
        self.read_call: tuple[object, ...] | None = None

    async def ingest_batch(self, identity, device_id, batch):
        self.ingest_call = (identity, device_id, batch)
        return BatchReceipt(batch_id=batch.batch_id, status="RECEIVED", duplicate=False)

    async def list_telemetry(
        self, organization_id, device_id, *, actor_id, assigned_only, metric_name, limit
    ):
        self.read_call = (
            organization_id,
            device_id,
            actor_id,
            assigned_only,
            metric_name,
            limit,
        )
        return (
            TelemetrySample(
                id=UUID(int=5),
                device_id=device_id,
                metric_name="cpu.usage_percent",
                metric_value=42.5,
                recorded_at=datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
                labels={},
            ),
        )

    async def get_agent_batch_status(self, _identity, _device_id, batch_id):
        return BatchStatusRecord(batch_id, "PROCESSING", 1, 0, None, None)

    async def get_agent_batch_statuses(self, _identity, _device_id, batch_ids):
        return tuple(
            BatchStatusRecord(batch_id, "RECEIVED", 0, 0, None, None)
            for batch_id in batch_ids
        )

    async def authorize_retry(self, *_arguments):
        return BatchStatusRecord(BATCH_ID, "AWAITING_REUPLOAD", 0, 1, None, None)

    async def reupload_batch(self, _identity, _device_id, batch_id, _payload):
        return BatchReceipt(batch_id, "RECEIVED", False)

    async def export_diagnostics(self, *_arguments):
        return BatchDiagnostics(
            BATCH_ID,
            "DLQ",
            3,
            0,
            "a" * 64,
            "INVALID_PAYLOAD",
            "Metric payload failed validation",
            datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
            None,
        )

    async def decide_exhausted_batch(self, *_arguments):
        return BatchStatusRecord(
            BATCH_ID, "DLQ_EXHAUSTED", 3, 3, "PROCESSING_ERROR", "PURGE_LOCAL"
        )


def _client(
    application: Application,
    permissions: set[str] | None = None,
) -> TestClient:
    app = FastAPI()
    app.state.metric_agent_authenticator = AgentAuthenticator()
    app.state.metric_ingest_rate_limiter = RateLimiter()
    app.state.metrics_application = application
    app.state.session_application = SessionApplication(permissions)
    app.state.session_request_rate_limiter = SessionRateLimiter()
    install_error_handlers(app)
    app.include_router(metrics_router, prefix="/api/v1")
    return TestClient(app, base_url="https://testserver")


def _payload() -> dict[str, object]:
    incomplete = MetricBatchInput.model_validate(
        {
            "batch_id": str(BATCH_ID),
            "payload_digest": "0" * 64,
            "samples": [
                {
                    "metric_name": "cpu.usage_percent",
                    "metric_value": 42.5,
                    "recorded_at": "2026-08-24T12:00:00Z",
                }
            ],
        }
    )
    return {
        **incomplete.model_dump(mode="json"),
        "payload_digest": incomplete.computed_digest(),
    }


def test_agent_ingest_returns_202_only_for_authenticated_own_device() -> None:
    application = Application()
    client = _client(application)

    response = client.post(
        f"/api/v1/devices/{DEVICE_ID}/metrics/batches",
        headers={"Authorization": "Bearer agent-token"},
        json=_payload(),
    )

    assert response.status_code == 202
    assert response.json() == {
        "batch_id": str(BATCH_ID),
        "status": "RECEIVED",
        "duplicate": False,
    }
    assert application.ingest_call is not None


def test_agent_ingest_requires_bearer_authentication() -> None:
    application = Application()
    client = _client(application)

    response = client.post(
        f"/api/v1/devices/{DEVICE_ID}/metrics/batches",
        json=_payload(),
    )

    assert response.status_code == 401
    assert application.ingest_call is None


def test_agent_ingest_rejects_payload_over_512_kib() -> None:
    application = Application()
    client = _client(application)
    body = json.dumps({**_payload(), "padding": "x" * (512 * 1024)})

    response = client.post(
        f"/api/v1/devices/{DEVICE_ID}/metrics/batches",
        headers={
            "Authorization": "Bearer agent-token",
            "Content-Type": "application/json",
        },
        content=body,
    )

    assert response.status_code == 413
    assert application.ingest_call is None
    assert "padding" not in response.text


def test_telemetry_read_uses_session_tenant_and_trimmed_output() -> None:
    application = Application()
    client = _client(application)
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")

    response = client.get(
        f"/api/v1/devices/{DEVICE_ID}/metrics/telemetry",
        params={"limit": 25, "organization_id": str(UUID(int=99))},
    )

    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "id": str(UUID(int=5)),
        "device_id": str(DEVICE_ID),
        "metric_name": "cpu.usage_percent",
        "metric_value": 42.5,
        "recorded_at": "2026-08-24T12:00:00Z",
        "labels": {},
    }
    assert application.read_call == (ORG_ID, DEVICE_ID, UUID(int=4), True, None, 25)


def test_telemetry_read_all_permission_disables_assignment_filter() -> None:
    application = Application()
    client = _client(
        application,
        {"metrics:read_telemetry", "metrics:read_all"},
    )
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")

    response = client.get(f"/api/v1/devices/{DEVICE_ID}/metrics/telemetry")

    assert response.status_code == 200
    assert application.read_call is not None
    assert application.read_call[3] is False


def test_agent_can_query_batch_statuses_and_reupload_authorized_payload() -> None:
    client = _client(Application())
    headers = {"Authorization": "Bearer agent-token"}

    query = client.post(
        f"/api/v1/devices/{DEVICE_ID}/metrics/batches/status-query",
        headers=headers,
        json={"batch_ids": [str(BATCH_ID)]},
    )
    reupload_payload = _payload()
    reupload_payload.pop("batch_id")
    reupload = client.post(
        f"/api/v1/devices/{DEVICE_ID}/metrics/batches/{BATCH_ID}/reupload",
        headers=headers,
        json=reupload_payload,
    )

    assert query.status_code == 200
    assert query.json()["statuses"][str(BATCH_ID)]["status"] == "RECEIVED"
    assert reupload.status_code == 202
    assert reupload.json()["status"] == "RECEIVED"


def test_admin_dlq_mutations_require_csrf_and_return_trimmed_records() -> None:
    client = _client(Application())
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")
    retry_url = f"/api/v1/devices/{DEVICE_ID}/metrics/batches/{BATCH_ID}/retry"

    rejected = client.post(retry_url, json={"reason": "operator approved"})

    client.cookies.set(CSRF_COOKIE_NAME, "csrf")
    headers = {"X-CSRF-Token": "csrf"}
    retry = client.post(
        retry_url,
        headers=headers,
        json={"reason": "operator approved"},
    )
    decision = client.post(
        f"/api/v1/devices/{DEVICE_ID}/metrics/batches/{BATCH_ID}/decision",
        headers=headers,
        json={"action": "PURGE_LOCAL", "reason": "disk protection"},
    )

    assert rejected.status_code == 403
    assert retry.status_code == 200
    assert retry.json()["reprocess_count"] == 1
    assert decision.status_code == 200
    assert decision.json()["decision"] == "PURGE_LOCAL"


def test_diagnostics_never_returns_payload() -> None:
    client = _client(Application())
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")

    response = client.get(
        f"/api/v1/devices/{DEVICE_ID}/metrics/batches/{BATCH_ID}/export-diagnostics"
    )

    assert response.status_code == 200
    assert response.json()["error_code"] == "INVALID_PAYLOAD"
    assert "payload_json" not in response.text
