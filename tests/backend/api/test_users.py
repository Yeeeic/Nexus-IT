from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import install_error_handlers
from backend.app.api.users import users_router
from backend.app.auth.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from backend.app.auth.session import SessionIdentity
from backend.app.auth.session_tokens import hash_token
from backend.app.users.service import UserSummary


USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ORG_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
SESSION_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


class SessionApplication:
    async def authenticate(
        self,
        _session_token: str,
        *,
        require_organization: bool = True,
    ) -> SessionIdentity:
        assert require_organization
        return SessionIdentity(
            session_id=SESSION_ID,
            organization_id=ORG_ID,
            user_id=USER_ID,
            csrf_token_hash=hash_token("csrf"),
            permissions=frozenset({"users:manage"}),
        )


class RateLimiter:
    async def allow(self, _session_id: UUID) -> None:
        return None


class Directory:
    def __init__(self) -> None:
        self.call: tuple[UUID, int, UUID | None] | None = None
        self.created = False

    async def list_users(
        self,
        organization_id: UUID,
        *,
        actor_id: UUID,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[tuple[UserSummary, ...], UUID | None]:
        self.call = (organization_id, limit, after_id)
        assert actor_id == USER_ID
        return (
            (
                UserSummary(
                    id=USER_ID,
                    email="member@example.test",
                    full_name="Member",
                    is_active=True,
                ),
            ),
            None,
        )

    async def create_user(self, *_args: object, **_kwargs: object) -> UserSummary:
        self.created = True
        return UserSummary(USER_ID, "member@example.test", "Member", True)


def build_client(directory: Directory) -> TestClient:
    app = FastAPI()
    app.state.session_application = SessionApplication()
    app.state.session_request_rate_limiter = RateLimiter()
    app.state.user_directory = directory
    install_error_handlers(app)
    app.include_router(users_router, prefix="/api/v1")
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")
    return client


def test_user_directory_derives_tenant_and_excludes_sensitive_fields() -> None:
    directory = Directory()
    app = FastAPI()
    app.state.session_application = SessionApplication()
    app.state.session_request_rate_limiter = RateLimiter()
    app.state.user_directory = directory
    install_error_handlers(app)
    app.include_router(users_router, prefix="/api/v1")
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")

    response = client.get(
        "/api/v1/users",
        params={"limit": 25, "organization_id": str(UUID(int=1))},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(USER_ID),
                "email": "member@example.test",
                "full_name": "Member",
                "is_active": True,
            }
        ],
        "next_cursor": None,
    }
    assert "password" not in response.text.lower()
    assert directory.call == (ORG_ID, 25, None)


def test_user_directory_bounds_page_size_before_query() -> None:
    directory = Directory()
    app = FastAPI()
    app.state.session_application = SessionApplication()
    app.state.session_request_rate_limiter = RateLimiter()
    app.state.user_directory = directory
    install_error_handlers(app)
    app.include_router(users_router, prefix="/api/v1")
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")

    response = client.get("/api/v1/users", params={"limit": 101})

    assert response.status_code == 422
    assert directory.call is None


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    (
        (
            "post",
            "/api/v1/users",
            {
                "email": "member@example.test",
                "full_name": "Member",
                "password": "SecurePassword123",
                "role": "READER",
            },
        ),
        ("patch", f"/api/v1/users/{USER_ID}/status", {"is_active": False}),
        ("post", f"/api/v1/users/{USER_ID}/revoke-sessions", None),
        ("delete", f"/api/v1/users/{USER_ID}", None),
    ),
)
def test_user_mutations_require_matching_csrf_cookie_and_header(
    method: str,
    path: str,
    json_body: dict[str, object] | None,
) -> None:
    directory = Directory()
    client = build_client(directory)

    response = client.request(method, path, json=json_body)

    assert response.status_code == 403
    assert directory.created is False


def test_user_creation_rejects_weak_password_before_directory_call() -> None:
    directory = Directory()
    client = build_client(directory)
    client.cookies.set(CSRF_COOKIE_NAME, "csrf")

    response = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": "csrf"},
        json={
            "email": "member@example.test",
            "full_name": "Member",
            "password": "alllettersbutnodigits",
            "role": "READER",
        },
    )

    assert response.status_code == 422
    assert directory.created is False


def test_user_creation_accepts_strong_password_with_valid_csrf() -> None:
    directory = Directory()
    client = build_client(directory)
    client.cookies.set(CSRF_COOKIE_NAME, "csrf")

    response = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": "csrf"},
        json={
            "email": "member@example.test",
            "full_name": "Member",
            "password": "SecurePassword123",
            "role": "READER",
        },
    )

    assert response.status_code == 201
    assert directory.created is True
