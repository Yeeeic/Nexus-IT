"""Validated application configuration sourced exclusively from the environment."""

import base64
import binascii
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class ConfigurationError(ValueError):
    """Raised when required runtime configuration is missing or unsafe."""


def parse_allowed_origins(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    origins = tuple(origin.strip() for origin in value.split(",") if origin.strip())
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
        ):
            raise ConfigurationError("NEXUS_ALLOWED_ORIGINS contains an invalid origin")
    return origins


class AppSettings(BaseModel):
    """Security-sensitive runtime settings."""

    model_config = ConfigDict(extra="forbid")

    server_pepper: SecretStr = Field(min_length=32)
    allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "AppSettings":
        """Load settings without accepting fallback values for required secrets."""
        server_pepper = environ.get("NEXUS_SERVER_PEPPER")
        if server_pepper is None or len(server_pepper) < 32:
            raise ConfigurationError(
                "NEXUS_SERVER_PEPPER must contain at least 32 characters"
            )

        return cls.model_validate(
            {
                "server_pepper": server_pepper,
                "allowed_origins": parse_allowed_origins(
                    environ.get("NEXUS_ALLOWED_ORIGINS")
                ),
            }
        )


class RemoteActionSettings(BaseModel):
    """Ed25519 signing material loaded from secret-managed environment values."""

    model_config = ConfigDict(extra="forbid")

    private_key: SecretStr
    key_version: int = Field(ge=1)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "RemoteActionSettings":
        encoded_key = environ.get("NEXUS_ACTION_PRIVATE_KEY")
        try:
            raw_key = base64.b64decode(encoded_key or "", validate=True)
        except (binascii.Error, ValueError) as error:
            raise ConfigurationError(
                "NEXUS_ACTION_PRIVATE_KEY must be a base64 Ed25519 private key"
            ) from error
        if len(raw_key) != 32:
            raise ConfigurationError(
                "NEXUS_ACTION_PRIVATE_KEY must decode to exactly 32 bytes"
            )
        try:
            return cls.model_validate(
                {
                    "private_key": encoded_key,
                    "key_version": environ.get("NEXUS_ACTION_KEY_VERSION", "1"),
                }
            )
        except ValidationError as error:
            raise ConfigurationError(
                "Remote action signing configuration is invalid"
            ) from error


class AttachmentSettings(BaseModel):
    """Private storage directory settings for ticket attachments."""

    model_config = ConfigDict(extra="forbid")

    root_directory: str = Field(min_length=1, max_length=1024)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "AttachmentSettings":
        root = environ.get("NEXUS_ATTACHMENTS_ROOT", "/var/lib/nexus/attachments")
        path = Path(root)
        if not path.is_absolute():
            raise ConfigurationError(
                "NEXUS_ATTACHMENTS_ROOT must be an absolute path"
            )
        try:
            return cls.model_validate({"root_directory": str(path.resolve())})
        except ValidationError as error:
            raise ConfigurationError(
                "Attachment storage configuration is invalid"
            ) from error


class DatabaseSettings(BaseModel):
    """Minimum-privilege application database connection settings."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        min_length=1,
        max_length=253,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    port: int = Field(ge=1, le=65535)
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    user: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    password: SecretStr = Field(min_length=16)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "DatabaseSettings":
        values = {
            "host": environ.get("NEXUS_DATABASE_HOST", "postgres"),
            "port": environ.get("NEXUS_DATABASE_PORT", "5432"),
            "name": environ.get("NEXUS_DATABASE_NAME", "nexus_it"),
            "user": environ.get("NEXUS_DATABASE_USER"),
            "password": environ.get("NEXUS_DATABASE_PASSWORD"),
        }
        try:
            settings = cls.model_validate(values)
        except ValidationError as error:
            raise ConfigurationError(
                "Runtime database configuration is missing or invalid"
            ) from error

        forbidden_users = {
            "postgres",
            "root",
            "nexus_admin",
            "nexus_app_user",
            "nexus_auth_user",
            "nexus_bootstrap",
        }
        if settings.user.lower() in forbidden_users:
            raise ConfigurationError(
                "A dedicated runtime database principal is required"
            )
        return settings


class RedisSettings(BaseModel):
    """Private Redis connection used only for ephemeral coordination."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        min_length=1,
        max_length=253,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    port: int = Field(ge=1, le=65535)
    database: int = Field(ge=0, le=15)
    password: SecretStr = Field(min_length=16)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "RedisSettings":
        try:
            return cls.model_validate(
                {
                    "host": environ.get("NEXUS_REDIS_HOST", "redis"),
                    "port": environ.get("NEXUS_REDIS_PORT", "6379"),
                    "database": environ.get("NEXUS_REDIS_DATABASE", "0"),
                    "password": environ.get("NEXUS_REDIS_PASSWORD"),
                }
            )
        except ValidationError as error:
            raise ConfigurationError(
                "Redis configuration is missing or invalid"
            ) from error


class EmailSettings(BaseModel):
    """TLS-only SMTP delivery settings for password-reset messages."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        min_length=1,
        max_length=253,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$",
    )
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=3, max_length=255)
    password: SecretStr = Field(min_length=16)
    sender: str = Field(min_length=3, max_length=255)
    password_reset_url: str = Field(min_length=12, max_length=2048)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "EmailSettings":
        try:
            settings = cls.model_validate(
                {
                    "host": environ.get("NEXUS_SMTP_HOST"),
                    "port": environ.get("NEXUS_SMTP_PORT", "587"),
                    "username": environ.get("NEXUS_SMTP_USERNAME"),
                    "password": environ.get("NEXUS_SMTP_PASSWORD"),
                    "sender": environ.get("NEXUS_SMTP_FROM"),
                    "password_reset_url": environ.get(
                        "NEXUS_PASSWORD_RESET_URL"
                    ),
                }
            )
        except ValidationError as error:
            raise ConfigurationError(
                "Email delivery configuration is missing or invalid"
            ) from error

        for address in (settings.username, settings.sender):
            if (
                address.count("@") != 1
                or any(character.isspace() for character in address)
            ):
                raise ConfigurationError("Email address configuration is invalid")
        parsed_url = urlsplit(settings.password_reset_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ConfigurationError("Password reset URL must be a clean HTTPS URL")
        return settings
