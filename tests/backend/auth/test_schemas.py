import pytest
from pydantic import ValidationError

from backend.app.auth.schemas import LoginRequest, normalize_email


def test_normalize_email_applies_strip_lowercase_and_unicode_nfc() -> None:
    assert normalize_email("  U\u0308SER@EXAMPLE.COM  ") == "üser@example.com"


def test_login_request_normalizes_email_without_changing_password() -> None:
    request = LoginRequest(
        email="  User@Example.COM ",
        password="  password whitespace stays  ",
    )

    assert request.email == "user@example.com"
    assert request.password.get_secret_value() == "  password whitespace stays  "


def test_login_request_rejects_protected_or_unknown_fields() -> None:
    with pytest.raises(ValidationError) as error:
        LoginRequest.model_validate(
            {
                "email": "user@example.com",
                "password": "valid password",
                "organization_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "role": "ADMIN",
            }
        )

    assert {item["type"] for item in error.value.errors()} == {"extra_forbidden"}


@pytest.mark.parametrize(
    "email",
    ["missing-at.example.com", "@example.com", "user@", "user @example.com"],
)
def test_login_request_rejects_invalid_email(email: str) -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email=email, password="valid password")


def test_login_request_never_exposes_password_in_representations() -> None:
    password = "a password that must remain secret"
    request = LoginRequest(email="user@example.com", password=password)

    assert password not in repr(request)
    assert password not in str(request)
    assert password not in request.model_dump_json()
