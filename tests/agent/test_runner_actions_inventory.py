from __future__ import annotations

import base64
import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent.nexus_agent.actions import (
    AgentActionOrder,
    SQLiteActionStore,
    build_signing_payload,
)
from agent.nexus_agent.storage import LocalQueue
from agent.run_agent import (
    HttpActionClient,
    HttpInventorySender,
    NexusAgent,
    collect_system_inventory,
    make_action_handlers,
    parse_public_keys,
)


DEVICE_ID = "11111111-1111-4111-8111-111111111111"
ORG_ID = "22222222-2222-4222-8222-222222222222"
ACTION_ID = "33333333-3333-4333-8333-333333333333"
NONCE = "44444444-4444-4444-8444-444444444444"


class FakeSystemProbe:
    def cpu_percent(self) -> float:
        return 25.0

    def memory(self) -> Mapping[str, int | float | None]:
        return {"total_bytes": 16 * 1024 * 1024 * 1024, "available_bytes": 8 * 1024 * 1024 * 1024, "used_percent": 50.0}

    def disks(self) -> list[dict[str, object]]:
        return [{"mount": "C:\\", "total_bytes": 500_000_000_000, "used_bytes": 200_000_000_000, "free_bytes": 300_000_000_000}]

    def networks(self) -> list[dict[str, object]]:
        return [{"host": "my-host", "addresses": ["192.168.1.50"]}]

    def processes(self) -> list[dict[str, object]]:
        return []

    def services(self) -> list[dict[str, object]]:
        return [{"name": "Spooler", "display_name": "Print Spooler", "status": "RUNNING", "start_type": "AUTO"}]

    def smart(self) -> list[dict[str, object]]:
        return []


def test_collect_system_inventory_returns_valid_payload() -> None:
    probe = FakeSystemProbe()
    inventory = collect_system_inventory(probe)

    assert "hardware" in inventory
    hw = inventory["hardware"]
    assert isinstance(hw, dict)
    assert hw["memory_bytes"] == 16 * 1024 * 1024 * 1024
    assert hw["physical_cores"] >= 1
    assert hw["logical_processors"] >= 1

    assert "services" in inventory
    services = inventory["services"]
    assert isinstance(services, list)
    assert len(services) == 1
    assert services[0]["name"] == "Spooler"
    assert services[0]["status"] == "RUNNING"


def test_parse_public_keys_from_dict_and_env() -> None:
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    b64_pub = base64.b64encode(pub_bytes).decode("ascii")

    keys = parse_public_keys({"1": b64_pub})
    assert 1 in keys
    assert keys[1] == pub_bytes

    keys_env = parse_public_keys({}, environment={"NEXUS_AGENT_PUBLIC_KEYS": json.dumps({"2": b64_pub})})
    assert 2 in keys_env
    assert keys_env[2] == pub_bytes


def test_agent_polls_verifies_executes_and_reports_ed25519_action(tmp_path: Path) -> None:
    # 1. Setup crypto
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    public_keys = {1: pub_bytes}

    now = datetime.now(timezone.utc)
    issued_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_str = (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    order = AgentActionOrder(
        action_execution_id=UUID(ACTION_ID),
        organization_id=UUID(ORG_ID),
        device_id=UUID(DEVICE_ID),
        nonce=UUID(NONCE),
        action_name="flush_dns",
        action_version=1,
        key_version=1,
        issued_at=issued_str,
        expires_at=expires_str,
        order_digest="",
        signature="",
        parameters_canonical="{}",
    )
    payload = build_signing_payload(order)
    sig_raw = priv.sign(payload)
    sig_str = base64.urlsafe_b64encode(sig_raw).decode("ascii").rstrip("=")
    order_digest = hashlib.sha256(payload).hexdigest()

    action_record = {
        "id": ACTION_ID,
        "organization_id": ORG_ID,
        "device_id": DEVICE_ID,
        "nonce": NONCE,
        "action_name": "flush_dns",
        "action_version": 1,
        "key_version": 1,
        "issued_at": order.issued_at,
        "expires_at": order.expires_at,
        "order_digest": order_digest,
        "signature": sig_str,
        "parameters_canonical": "{}",
    }

    # 3. Setup Agent and mock client
    action_store = SQLiteActionStore(tmp_path / "actions.sqlite3")
    queue = LocalQueue(tmp_path / "agent.db")

    executed_actions: list[dict[str, object]] = []

    def mock_flush_dns(_params: dict[str, object]) -> tuple[int, str]:
        executed_actions.append(_params)
        return 0, "DNS cache flushed"

    handlers = {"flush_dns": mock_flush_dns}

    agent = NexusAgent(
        server_url="https://localhost",
        device_id=DEVICE_ID,
        device_token="test-token",
        queue=queue,
        action_store=action_store,
        public_keys=public_keys,
        probe=FakeSystemProbe(),
        action_handlers=handlers,
    )

    # Mock action client calls
    acknowledged_ids: list[str] = []
    reported_results: list[dict[str, object]] = []

    agent.action_client.poll_actions = lambda: [action_record]  # type: ignore[method-assign]
    agent.action_client.acknowledge_action = lambda aid: acknowledged_ids.append(aid) or True  # type: ignore[method-assign]
    agent.action_client.report_result = lambda aid, status, exit_code, output_summary: (  # type: ignore[method-assign]
        reported_results.append({"action_id": aid, "status": status, "exit_code": exit_code, "output_summary": output_summary})
        or True
    )

    # 4. Execute polling & processing
    count = agent.poll_and_execute_actions()

    assert count == 1
    assert acknowledged_ids == [ACTION_ID]
    assert len(executed_actions) == 1
    assert len(reported_results) == 1
    assert reported_results[0]["status"] == "SUCCEEDED"
    assert reported_results[0]["exit_code"] == 0
    assert reported_results[0]["output_summary"] == "DNS cache flushed"
    assert action_store.status(UUID(ACTION_ID)) == "SUCCEEDED"


def test_action_handlers_enforce_strictly_closed_catalog() -> None:
    handlers = make_action_handlers()
    assert set(handlers.keys()) == {
        "restart_service",
        "flush_dns",
        "collect_extended_diagnostics",
        "reboot_system",
    }
