import base64

import pytest

from backend.app.core.config import (
    AppSettings,
    AttachmentSettings,
    ConfigurationError,
    DatabaseSettings,
    EmailSettings,
    RedisSettings,
    RemoteActionSettings,
)


def test_settings_reject_missing_server_pepper() -> None:
    with pytest.raises(ConfigurationError):
        AppSettings.from_environment({})


def test_settings_reject_short_server_pepper() -> None:
    secret = "too-short"

    with pytest.raises(ConfigurationError) as error:
        AppSettings.from_environment({"NEXUS_SERVER_PEPPER": "too-short"})

    assert secret not in str(error.value)


def test_settings_hide_server_pepper_from_representations() -> None:
    secret = "a-local-test-pepper-with-at-least-32-bytes"

    settings = AppSettings.from_environment({"NEXUS_SERVER_PEPPER": secret})

    assert settings.server_pepper.get_secret_value() == secret
    assert secret not in repr(settings)
    assert secret not in str(settings)


def test_settings_parse_only_explicit_safe_cors_origins() -> None:
    settings = AppSettings.from_environment(
        {
            "NEXUS_SERVER_PEPPER": "a-local-test-pepper-with-at-least-32-bytes",
            "NEXUS_ALLOWED_ORIGINS": (
                "https://app.example.test,http://localhost:5173"
            ),
        }
    )

    assert settings.allowed_origins == (
        "https://app.example.test",
        "http://localhost:5173",
    )

    with pytest.raises(ConfigurationError):
        AppSettings.from_environment(
            {
                "NEXUS_SERVER_PEPPER": "a-local-test-pepper-with-at-least-32-bytes",
                "NEXUS_ALLOWED_ORIGINS": "https://app.example.test/path",
            }
        )


def test_remote_action_settings_require_exact_private_key_and_positive_version() -> None:
    encoded_key = base64.b64encode(bytes(range(32))).decode("ascii")
    settings = RemoteActionSettings.from_environment(
        {
            "NEXUS_ACTION_PRIVATE_KEY": encoded_key,
            "NEXUS_ACTION_KEY_VERSION": "2",
        }
    )

    assert settings.key_version == 2
    assert settings.private_key.get_secret_value() == encoded_key
    assert encoded_key not in repr(settings)

    for environment in (
        {},
        {"NEXUS_ACTION_PRIVATE_KEY": "not-base64"},
        {"NEXUS_ACTION_PRIVATE_KEY": base64.b64encode(b"short").decode("ascii")},
        {
            "NEXUS_ACTION_PRIVATE_KEY": encoded_key,
            "NEXUS_ACTION_KEY_VERSION": "0",
        },
    ):
        with pytest.raises(ConfigurationError):
            RemoteActionSettings.from_environment(environment)


def test_database_settings_require_dedicated_runtime_credentials() -> None:
    with pytest.raises(ConfigurationError):
        DatabaseSettings.from_environment({})

    with pytest.raises(ConfigurationError):
        DatabaseSettings.from_environment(
            {
                "NEXUS_DATABASE_USER": "nexus_bootstrap",
                "NEXUS_DATABASE_PASSWORD": "not-a-real-secret",
            }
        )


def test_database_settings_are_bounded_and_hide_password() -> None:
    secret = "runtime-only-password"
    settings = DatabaseSettings.from_environment(
        {
            "NEXUS_DATABASE_HOST": "postgres",
            "NEXUS_DATABASE_PORT": "5432",
            "NEXUS_DATABASE_NAME": "nexus_it",
            "NEXUS_DATABASE_USER": "nexus_runtime",
            "NEXUS_DATABASE_PASSWORD": secret,
        }
    )

    assert settings.host == "postgres"
    assert settings.port == 5432
    assert settings.name == "nexus_it"
    assert settings.user == "nexus_runtime"
    assert settings.password.get_secret_value() == secret
    assert secret not in repr(settings)
    assert secret not in str(settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("NEXUS_DATABASE_HOST", ""),
        ("NEXUS_DATABASE_PORT", "0"),
        ("NEXUS_DATABASE_PORT", "65536"),
        ("NEXUS_DATABASE_NAME", "name with spaces"),
        ("NEXUS_DATABASE_USER", "root"),
    ],
)
def test_database_settings_reject_unsafe_values(field: str, value: str) -> None:
    environment = {
        "NEXUS_DATABASE_HOST": "postgres",
        "NEXUS_DATABASE_PORT": "5432",
        "NEXUS_DATABASE_NAME": "nexus_it",
        "NEXUS_DATABASE_USER": "nexus_runtime",
        "NEXUS_DATABASE_PASSWORD": "not-a-real-secret",
    }
    environment[field] = value

    with pytest.raises(ConfigurationError):
        DatabaseSettings.from_environment(environment)


def test_redis_settings_require_and_hide_independent_password() -> None:
    with pytest.raises(ConfigurationError):
        RedisSettings.from_environment({})

    secret = "independent-redis-password"
    settings = RedisSettings.from_environment(
        {
            "NEXUS_REDIS_HOST": "redis",
            "NEXUS_REDIS_PORT": "6379",
            "NEXUS_REDIS_DATABASE": "0",
            "NEXUS_REDIS_PASSWORD": secret,
        }
    )

    assert settings.host == "redis"
    assert settings.port == 6379
    assert settings.database == 0
    assert settings.password.get_secret_value() == secret
    assert secret not in repr(settings)
    assert secret not in str(settings)


def test_attachment_settings_valid_and_rejects_relative_path(tmp_path) -> None:
    settings = AttachmentSettings.from_environment(
        {"NEXUS_ATTACHMENTS_ROOT": str(tmp_path.resolve())}
    )
    assert settings.root_directory == str(tmp_path.resolve())

    with pytest.raises(ConfigurationError, match="NEXUS_ATTACHMENTS_ROOT must be an absolute path"):
        AttachmentSettings.from_environment({"NEXUS_ATTACHMENTS_ROOT": "relative/path"})


def test_email_settings_require_tls_url_and_hide_password() -> None:
    secret = "smtp-runtime-password"
    settings = EmailSettings.from_environment(
        {
            "NEXUS_SMTP_HOST": "smtp.example.test",
            "NEXUS_SMTP_PORT": "587",
            "NEXUS_SMTP_USERNAME": "nexus@example.test",
            "NEXUS_SMTP_PASSWORD": secret,
            "NEXUS_SMTP_FROM": "nexus@example.test",
            "NEXUS_PASSWORD_RESET_URL": "https://app.example.test/reset-password",
        }
    )

    assert settings.port == 587
    assert settings.password.get_secret_value() == secret
    assert secret not in repr(settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("NEXUS_PASSWORD_RESET_URL", "http://app.example.test/reset"),
        ("NEXUS_SMTP_FROM", "bad\nBcc: victim@example.test"),
        ("NEXUS_SMTP_PORT", "0"),
    ],
)
def test_email_settings_reject_unsafe_values(field: str, value: str) -> None:
    environment = {
        "NEXUS_SMTP_HOST": "smtp.example.test",
        "NEXUS_SMTP_PORT": "587",
        "NEXUS_SMTP_USERNAME": "nexus@example.test",
        "NEXUS_SMTP_PASSWORD": "smtp-runtime-password",
        "NEXUS_SMTP_FROM": "nexus@example.test",
        "NEXUS_PASSWORD_RESET_URL": "https://app.example.test/reset-password",
    }
    environment[field] = value

    with pytest.raises(ConfigurationError):
        EmailSettings.from_environment(environment)
