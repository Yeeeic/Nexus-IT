from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.run_agent import (
    _cpu_percent_between,
    load_config,
    resolve_identity,
    validate_server_url,
)


DEVICE_ID = "11111111-1111-4111-8111-111111111111"


def test_server_requires_https_outside_explicit_loopback_development() -> None:
    assert validate_server_url("https://nexus.example.test/", allow_insecure_http=False) == (
        "https://nexus.example.test"
    )
    assert validate_server_url("http://127.0.0.1:8000", allow_insecure_http=True) == (
        "http://127.0.0.1:8000"
    )
    with pytest.raises(ValueError, match="HTTPS is required"):
        validate_server_url("http://nexus.example.test", allow_insecure_http=True)


def test_runtime_config_rejects_embedded_device_token(tmp_path: Path) -> None:
    path = tmp_path / "agent_config.json"
    path.write_text(json.dumps({"device_id": DEVICE_ID, "device_token": "secret"}), "utf-8")

    with pytest.raises(ValueError, match="unsupported fields"):
        load_config(path)


def test_device_token_is_required_from_environment() -> None:
    with pytest.raises(ValueError, match="device identity missing"):
        resolve_identity({"device_id": DEVICE_ID}, environment={})

    assert resolve_identity(
        {"device_id": DEVICE_ID}, environment={"NEXUS_AGENT_TOKEN": "token-value"}
    ) == (DEVICE_ID, "token-value")


def test_agent_parser_has_no_command_line_token_or_admin_credentials() -> None:
    source = Path("agent/run_agent.py").read_text("utf-8")
    assert '"--token"' not in source
    assert "NEXUS_ADMIN_PASSWORD" not in source
    assert "auto_enroll" not in source


def test_windows_cpu_usage_is_calculated_from_monotonic_system_time_deltas() -> None:
    assert _cpu_percent_between((100, 300, 200), (150, 400, 300)) == 75.0
    assert _cpu_percent_between((100, 300, 200), (100, 300, 200)) is None
