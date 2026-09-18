from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import install_error_handlers
from backend.app.auth.schemas import LoginRequest


def test_validation_error_response_never_echoes_password() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/login")
    def login(_: LoginRequest) -> dict[str, str]:
        return {"status": "unused"}

    password = "s" * 1025
    response = TestClient(app).post(
        "/login",
        json={"email": "user@example.com", "password": password},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["message"] == "Solicitud inválida"
    UUID(error["error_id"])
    assert password not in response.text
