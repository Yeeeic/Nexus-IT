from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.app.core.body_limit import RequestBodyLimitMiddleware


def test_body_limit_rejects_metric_body_before_endpoint_reads_it() -> None:
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware)
    called = False

    @app.post("/api/v1/devices/{device_id}/metrics/batches")
    async def receive_batch(device_id: str, request: Request) -> dict[str, object]:
        nonlocal called
        called = True
        return {"size": len(await request.body()), "device_id": device_id}

    response = TestClient(app).post(
        "/api/v1/devices/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/metrics/batches",
        content=b"x" * (512 * 1024 + 1),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert called is False


def test_body_limit_replays_bounded_body() -> None:
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware)

    @app.put("/api/v1/devices/{device_id}/inventory")
    async def receive_inventory(device_id: str, request: Request) -> dict[str, object]:
        return {"size": len(await request.body()), "device_id": device_id}

    response = TestClient(app).put(
        "/api/v1/devices/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/inventory",
        content=b"bounded",
    )

    assert response.status_code == 200
    assert response.json()["size"] == 7
