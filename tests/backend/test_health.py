import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import ConfigurationError
from backend.app.main import app, create_app


def test_health_reports_service_is_available() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-security-policy"].startswith(
        "default-src 'self'"
    )
    assert response.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains; preload"
    )
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == (
        "strict-origin-when-cross-origin"
    )
    assert response.headers["x-request-id"]


def test_cors_allows_only_explicit_origin() -> None:
    test_app = create_app(allowed_origins=("https://app.example.test",))
    client = TestClient(test_app)

    allowed = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://app.example.test",
            "Access-Control-Request-Method": "POST",
        },
    )
    denied = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == (
        "https://app.example.test"
    )
    assert "access-control-allow-origin" not in denied.headers


def test_runtime_starts_before_serving_and_closes_afterward() -> None:
    class BackgroundWorker:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        async def run_forever(self) -> None:
            self.started = True
            try:
                await asyncio.Event().wait()
            finally:
                self.stopped = True

        def stop(self) -> None:
            self.stopped = True

    class Runtime:
        login_application = object()
        session_application = object()
        session_request_rate_limiter = object()
        context_application = object()
        logout_application = object()
        password_reset_application = object()
        password_reset_request_application = object()
        user_directory = object()
        administration = object()
        device_service = object()
        agent_token_application = object()
        agent_request_rate_limiter = object()
        metrics_application = object()
        metric_ingest_rate_limiter = object()
        realtime_hub = object()
        support_application = object()
        metric_worker = BackgroundWorker()
        metric_maintenance_worker = BackgroundWorker()
        closed = False

        async def close(self) -> None:
            self.metric_worker.stop()
            self.metric_maintenance_worker.stop()
            self.closed = True

    runtime = Runtime()

    async def load_runtime(_environment: object) -> Runtime:
        return runtime

    test_app = create_app(load_runtime)

    with TestClient(test_app) as client:
        assert client.get("/health").status_code == 200
        assert "/api/v1/auth/login" in test_app.openapi()["paths"]
        assert "/api/v1/devices" in test_app.openapi()["paths"]
        assert "/api/v1/devices/{device_id}/metrics/batches" in (
            test_app.openapi()["paths"]
        )
        assert "/api/v1/tickets" in test_app.openapi()["paths"]
        assert runtime.metric_worker.started is True
        assert runtime.metric_maintenance_worker.started is True
        assert runtime.closed is False

    assert runtime.closed is True
    assert runtime.metric_worker.stopped is True
    assert runtime.metric_maintenance_worker.stopped is True


def test_runtime_fails_closed_when_required_secrets_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "NEXUS_SERVER_PEPPER",
        "NEXUS_DATABASE_USER",
        "NEXUS_DATABASE_PASSWORD",
        "NEXUS_MAINTENANCE_DATABASE_USER",
        "NEXUS_MAINTENANCE_DATABASE_PASSWORD",
        "NEXUS_REDIS_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ConfigurationError):
        with TestClient(create_app()):
            pass
