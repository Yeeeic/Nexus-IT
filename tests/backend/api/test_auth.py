from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.auth import auth_router
from backend.app.api.errors import install_error_handlers
from backend.app.auth.login import ActiveMembership, LoginResult, LoginStatus
from backend.app.auth.context import ContextSelectionResult
from backend.app.auth.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from backend.app.auth.rate_limit import (
    LoginRateLimitUnavailable,
    LoginRequestRateLimited,
)
from backend.app.auth.password_reset import (
    PasswordResetRejected,
    PasswordResetUnavailable,
)
from backend.app.auth.schemas import LoginOrganization, UserMeResponse
from backend.app.auth.service import AuthenticationRejected
from backend.app.auth.session import SessionRejected
from backend.app.auth.session_tokens import SessionSecrets, hash_token


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
SESSION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
SECRETS = SessionSecrets(
    session_id=SESSION_ID,
    session_token="private-session-token",
    session_token_hash=hash_token("private-session-token"),
    csrf_token="private-csrf-token",
    csrf_token_hash=hash_token("private-csrf-token"),
)


class FakeLoginApplication:
    def __init__(self, outcome: LoginResult | Exception) -> None:
        self.outcome = outcome
        self.call: dict[str, object] | None = None

    async def login(self, request: object, **context: object) -> LoginResult:
        self.call = {"request": request, **context}
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeContextApplication:
    def __init__(self) -> None:
        self.call: dict[str, object] | None = None

    async def select(self, **context: object) -> ContextSelectionResult:
        self.call = context
        return ContextSelectionResult(organization_id=ORG_ID, secrets=SECRETS)


class FakeLogoutApplication:
    def __init__(self) -> None:
        self.call: dict[str, object] | None = None

    async def logout(self, **context: object) -> None:
        self.call = context


class FakePasswordResetApplication:
    def __init__(self, outcome: Exception | None = None) -> None:
        self.outcome = outcome
        self.call: tuple[str, str] | None = None

    async def consume(
        self, token: str, new_password: str, **_context: str
    ) -> None:
        self.call = (token, new_password)
        if self.outcome is not None:
            raise self.outcome


class FakePasswordResetRequestApplication:
    def __init__(self, outcome: object = None) -> None:
        self.outcome = outcome
        self.request_call: dict[str, object] | None = None
        self.deliveries: list[object] = []

    async def request(self, email: str, **context: object) -> object:
        self.request_call = {"email": email, **context}
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    async def deliver(self, delivery: object) -> None:
        self.deliveries.append(delivery)


class FakeSessionApplication:
    def __init__(self, user_me: UserMeResponse | Exception | None = None) -> None:
        self.user_me = user_me

    async def get_me(self, session_token: str) -> UserMeResponse:
        if isinstance(self.user_me, Exception):
            raise self.user_me
        if self.user_me is None:
            raise SessionRejected
        return self.user_me


class FakeSessionRateLimiter:
    async def allow(self, _id: object) -> None:
        pass


def _client(
    outcome: LoginResult | Exception,
    user_me: UserMeResponse | Exception | None = None,
) -> tuple[TestClient, FakeLoginApplication]:
    application = FakeLoginApplication(outcome)
    app = FastAPI()
    app.state.login_application = application
    app.state.session_application = FakeSessionApplication(user_me)
    app.state.session_request_rate_limiter = FakeSessionRateLimiter()
    app.state.context_application = FakeContextApplication()
    app.state.logout_application = FakeLogoutApplication()
    app.state.password_reset_application = FakePasswordResetApplication()
    app.state.password_reset_request_application = (
        FakePasswordResetRequestApplication()
    )
    install_error_handlers(app)
    app.include_router(auth_router, prefix="/api/v1")
    return TestClient(app, base_url="https://testserver"), application


def test_login_emits_safe_cookies_and_explicit_response() -> None:
    client, application = _client(
        LoginResult(
            status=LoginStatus.AUTHENTICATED,
            organizations=(),
            secrets=SECRETS,
        )
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": " USER@EXAMPLE.TEST ", "password": "correct password"},
        headers={"user-agent": "Browser/1.0"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "AUTHENTICATED",
        "organizations": [],
    }
    assert SECRETS.session_token not in response.text
    assert SECRETS.csrf_token not in response.text
    assert response.cookies.get("__Host-nexus_session") == SECRETS.session_token
    assert response.cookies.get("__Host-nexus_csrf") == SECRETS.csrf_token
    assert application.call is not None
    request = application.call["request"]
    assert getattr(request, "email") == "user@example.test"
    assert application.call["user_agent"] == "Browser/1.0"
    assert application.call["ip_address"] == "testclient"


def test_login_returns_only_verified_options_for_multiple_memberships() -> None:
    client, _ = _client(
        LoginResult(
            status=LoginStatus.ORGANIZATION_SELECTION_REQUIRED,
            organizations=(
                ActiveMembership(
                    organization_id=ORG_ID,
                    organization_name="Org A",
                ),
            ),
            secrets=SECRETS,
        )
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.test", "password": "correct password"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ORGANIZATION_SELECTION_REQUIRED",
        "organizations": [{"id": str(ORG_ID), "name": "Org A"}],
    }


def test_login_rejection_is_uniform_and_never_sets_cookies() -> None:
    client, _ = _client(AuthenticationRejected())

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.test", "password": "wrong password"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "INVALID_CREDENTIALS",
            "message": "Credenciales inválidas o acceso no autorizado",
        }
    }
    assert response.headers.get_list("set-cookie") == []


def test_login_ip_limit_returns_retry_after_without_cookies() -> None:
    client, _ = _client(LoginRequestRateLimited(42))

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.test", "password": "password"},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert response.headers.get_list("set-cookie") == []


def test_login_fails_closed_when_protection_is_unavailable() -> None:
    client, _ = _client(LoginRateLimitUnavailable())

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.test", "password": "password"},
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "SERVICE_UNAVAILABLE",
        "message": "Servicio temporalmente no disponible",
    }
    assert "redis" not in response.text.lower()


def test_login_rejects_mass_assignment_before_application_call() -> None:
    client, application = _client(AuthenticationRejected())

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.test",
            "password": "password",
            "organization_id": str(ORG_ID),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert application.call is None


def test_context_selection_rotates_cookies_after_verified_choice() -> None:
    client, _ = _client(AuthenticationRejected())
    client.cookies.set(SESSION_COOKIE_NAME, "pending-session")
    client.cookies.set(CSRF_COOKIE_NAME, "pending-csrf")

    response = client.post(
        "/api/v1/auth/context",
        json={"organization_id": str(ORG_ID)},
        headers={"X-CSRF-Token": "pending-csrf"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "AUTHENTICATED"}
    assert response.cookies.get(SESSION_COOKIE_NAME) == SECRETS.session_token
    assert response.cookies.get(CSRF_COOKIE_NAME) == SECRETS.csrf_token


def test_context_selection_rejects_protected_fields() -> None:
    client, _ = _client(AuthenticationRejected())
    client.cookies.set(SESSION_COOKIE_NAME, "pending-session")

    response = client.post(
        "/api/v1/auth/context",
        json={
            "organization_id": str(ORG_ID),
            "user_id": str(UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")),
        },
    )

    assert response.status_code == 422


def test_logout_requires_csrf_and_clears_both_cookies() -> None:
    client, _ = _client(AuthenticationRejected())
    client.cookies.set(SESSION_COOKIE_NAME, "active-session")
    client.cookies.set(CSRF_COOKIE_NAME, "active-csrf")

    response = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": "active-csrf"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "SIGNED_OUT"}
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    assert all("Max-Age=0" in cookie for cookie in cookies)
    assert any(SESSION_COOKIE_NAME in cookie for cookie in cookies)
    assert any(CSRF_COOKIE_NAME in cookie for cookie in cookies)


def test_password_reset_confirmation_has_strict_safe_contract() -> None:
    client, _ = _client(AuthenticationRejected())
    reset = client.app.state.password_reset_application

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": f"{SESSION_ID}.private-reset-secret",
            "new_password": "New secure password 123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "PASSWORD_RESET_COMPLETE"}
    assert reset.call == (
        f"{SESSION_ID}.private-reset-secret",
        "New secure password 123",
    )
    assert "private-reset-secret" not in response.text
    assert "New secure password 123" not in response.text


def test_password_reset_rejection_is_uniform_and_leaks_no_token_state() -> None:
    client, _ = _client(AuthenticationRejected())
    client.app.state.password_reset_application = FakePasswordResetApplication(
        PasswordResetRejected()
    )

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": f"{SESSION_ID}.wrong-secret",
            "new_password": "New secure password 123",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "INVALID_PASSWORD_RESET",
        "message": "Solicitud de restablecimiento invÃ¡lida o expirada",
    }
    assert "wrong-secret" not in response.text


def test_password_reset_rejects_mass_assignment_and_weak_password() -> None:
    client, _ = _client(AuthenticationRejected())
    reset = client.app.state.password_reset_application

    extra_response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": f"{SESSION_ID}.secret",
            "new_password": "New secure password 123",
            "user_id": str(SESSION_ID),
        },
    )
    weak_response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": f"{SESSION_ID}.secret", "new_password": "short"},
    )

    assert extra_response.status_code == 422
    assert weak_response.status_code == 422
    assert reset.call is None


def test_password_reset_fails_closed_when_database_is_unavailable() -> None:
    client, _ = _client(AuthenticationRejected())
    client.app.state.password_reset_application = FakePasswordResetApplication(
        PasswordResetUnavailable()
    )

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": f"{SESSION_ID}.secret",
            "new_password": "New secure password 123",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_password_reset_is_rate_limited_before_expensive_hashing() -> None:
    client, _ = _client(AuthenticationRejected())
    client.app.state.password_reset_application = FakePasswordResetApplication(
        LoginRequestRateLimited(30)
    )

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": f"{SESSION_ID}.secret",
            "new_password": "New secure password 123",
        },
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_password_reset_request_is_uniform_for_existing_account() -> None:
    client, _ = _client(AuthenticationRejected())
    request_application = FakePasswordResetRequestApplication(object())
    client.app.state.password_reset_request_application = request_application

    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": " USER@EXAMPLE.TEST "},
        headers={"user-agent": "Browser/1.0"},
    )

    assert response.status_code == 202
    assert response.json() == {"status": "PASSWORD_RESET_REQUEST_ACCEPTED"}
    assert request_application.request_call == {
        "email": "user@example.test",
        "ip_address": "testclient",
        "user_agent": "Browser/1.0",
    }
    assert len(request_application.deliveries) == 1


def test_password_reset_request_is_same_for_unknown_account() -> None:
    client, _ = _client(AuthenticationRejected())
    request_application = FakePasswordResetRequestApplication(None)
    client.app.state.password_reset_request_application = request_application

    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "missing@example.test"},
    )

    assert response.status_code == 202
    assert response.json() == {"status": "PASSWORD_RESET_REQUEST_ACCEPTED"}
    assert request_application.deliveries == []


def test_password_reset_request_rejects_mass_assignment_and_rate_limits() -> None:
    client, _ = _client(AuthenticationRejected())
    request_application = FakePasswordResetRequestApplication(
        LoginRequestRateLimited(60)
    )
    client.app.state.password_reset_request_application = request_application

    invalid = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "user@example.test", "user_id": str(SESSION_ID)},
    )
    limited = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "user@example.test"},
    )

    assert invalid.status_code == 422
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_auth_me_returns_profile_and_permissions_when_authenticated() -> None:
    expected_profile = UserMeResponse(
        user_id=SESSION_ID,
        email="operator@example.test",
        full_name="Jane Operator",
        organization_id=ORG_ID,
        permissions=("tickets:read", "tickets:create"),
        available_organizations=(
            LoginOrganization(id=ORG_ID, name="Acme Corp"),
        ),
    )
    client, _ = _client(AuthenticationRejected(), user_me=expected_profile)
    client.cookies.set(SESSION_COOKIE_NAME, "valid-session-token")

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == str(SESSION_ID)
    assert data["email"] == "operator@example.test"
    assert data["full_name"] == "Jane Operator"
    assert data["organization_id"] == str(ORG_ID)
    assert data["permissions"] == ["tickets:read", "tickets:create"]
    assert len(data["available_organizations"]) == 1
    # Verify no secret leakage
    assert "password_hash" not in data
    assert "token_hash" not in data
    assert "csrf_token_hash" not in data


def test_auth_me_returns_profile_without_organization_when_no_context_selected() -> None:
    expected_profile = UserMeResponse(
        user_id=SESSION_ID,
        email="pending@example.test",
        full_name="Pending User",
        organization_id=None,
        permissions=(),
        available_organizations=(
            LoginOrganization(id=ORG_ID, name="Acme Corp"),
        ),
    )
    client, _ = _client(AuthenticationRejected(), user_me=expected_profile)
    client.cookies.set(SESSION_COOKIE_NAME, "valid-session-token")

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    data = response.json()
    assert data["organization_id"] is None
    assert data["permissions"] == []
    assert len(data["available_organizations"]) == 1


def test_auth_me_rejects_missing_cookie() -> None:
    client, _ = _client(AuthenticationRejected())
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_auth_me_rejects_invalid_session() -> None:
    client, _ = _client(AuthenticationRejected(), user_me=SessionRejected())
    client.cookies.set(SESSION_COOKIE_NAME, "expired-token")
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
