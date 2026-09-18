"""Real HTTP/backend/agent rehearsal inside the disposable Compose network.

Only extended diagnostics execute. No fake probe, signer, persistence or HTTP
transport is used. HTTP and manually echoed Secure cookies are restricted to
this isolated development network; browser cookie enforcement is a separate gate.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent.nexus_agent.actions import SQLiteActionStore
from agent.nexus_agent.storage import LocalQueue
from agent.run_agent import NexusAgent


BASE = "http://backend:8000"


class Console:
    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}

    def request(self, method: str, path: str, payload=None, *, expected=200, csrf=True):
        headers = {"Content-Type": "application/json", "Origin": "http://localhost:18080"}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            if csrf:
                headers["X-CSRF-Token"] = self.cookies["__Host-nexus_csrf"]
        request = urllib.request.Request(
            BASE + "/api/v1" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers, method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            assert response.status == expected, f"{method} {path}: HTTP {response.status}, expected {expected}"
            for value in response.headers.get_all("Set-Cookie", []):
                parsed = SimpleCookie(value)
                self.cookies.update({key: morsel.value for key, morsel in parsed.items()})
            raw = response.read()
            return json.loads(raw) if raw else None


def main() -> None:
    console = Console()
    console.request("GET", "/devices", expected=401)
    console.request("POST", "/auth/login", {
        "email": os.environ["NEXUS_E2E_EMAIL"],
        "password": os.environ["NEXUS_E2E_PASSWORD"],
    })
    console.request("GET", "/auth/me")
    console.request("POST", "/devices", {"hostname": "e2e-denied"}, csrf=False, expected=403)
    enrolled = console.request("POST", "/devices", {
        "hostname": "e2e-isolated-agent", "display_name": "Ensayo aislado E2E",
    }, expected=201)
    device_id = enrolled["id"]
    prefix = f"/devices/{device_id}"
    with tempfile.TemporaryDirectory(prefix="nexus-e2e-agent-") as temporary:
        state = Path(temporary)
        store = SQLiteActionStore(state / "actions.sqlite3")
        agent = NexusAgent(BASE, device_id, enrolled["token"], LocalQueue(state / "agent.db"),
            action_store=store,
            public_keys={1: base64.b64decode(os.environ["NEXUS_E2E_PUBLIC_KEY"])},
        )
        assert agent.collect_and_send_inventory().status_code == 200, "Inventory rejected"
        inventory = console.request("GET", prefix + "/inventory")
        assert inventory["hardware"]["memory_bytes"] > 0
        agent.collect_and_enqueue()
        outcome = agent.dispatcher.dispatch_once().outcome
        assert outcome in {"ACCEPTED", "ACKNOWLEDGED"}, f"Telemetry not durably accepted: {outcome}"
        for _ in range(15):
            telemetry = console.request("GET", prefix + "/metrics/telemetry")
            if telemetry["items"]:
                break
            time.sleep(2)
        assert telemetry["items"], "Worker did not publish telemetry within 30 seconds"
        console.request("POST", prefix + "/actions", {
            "action_name": "clear_cache", "parameters": {},
        }, expected=422)
        action = console.request("POST", prefix + "/actions", {
            "action_name": "collect_extended_diagnostics", "parameters": {"include_logs": False},
        }, expected=201)
        orders = agent.action_client.poll_actions()
        order = next(item for item in orders if item["id"] == action["id"])
        assert {"order_digest", "parameters_canonical", "action_version"} <= order.keys(), "Signed HTTP envelope incomplete"
        correct_keys = agent.public_keys
        agent.public_keys = {1: Ed25519PrivateKey.generate().public_key().public_bytes_raw()}
        assert agent.poll_and_execute_actions() == 0, "Untrusted signer accepted"
        agent.public_keys = correct_keys
        assert agent.poll_and_execute_actions() == 1, "Signed diagnostic did not execute"
        assert store.status(UUID(action["id"])) == "SUCCEEDED"
        assert agent.poll_and_execute_actions() == 0, "Diagnostic replay executed"
        # Idempotent result response proves the first report reached durable server state.
        with store._connect() as connection:
            row = connection.execute("SELECT exit_code, output_summary FROM action_states WHERE action_execution_id = ?", (action["id"],)).fetchone()
        request = urllib.request.Request(BASE + "/api/v1" + prefix + f"/actions/{action['id']}/result",
            data=json.dumps({"status": "SUCCEEDED", "exit_code": row["exit_code"], "output_summary": row["output_summary"]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + enrolled["token"]}, method="POST")
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        assert result["status"] == "COMPLETED" and result["is_replay"] is True
        replacement = console.request("POST", prefix + "/tokens", {}, expected=201)
        console.request("DELETE", prefix + f"/tokens/{enrolled['token_id']}", expected=204)
        assert agent.collect_and_send_inventory().status_code == 401, "Revoked token accepted"
        replacement_agent = NexusAgent(BASE, device_id, replacement["token"], LocalQueue(state / "replacement.db"))
        assert replacement_agent.collect_and_send_inventory().status_code == 200, "Replacement token rejected"
    print(json.dumps({"result": "PASS", "device_id": device_id,
        "checks": ["login", "csrf", "enrollment", "real_inventory", "durable_telemetry_ack", "worker_telemetry",
        "closed_catalog", "untrusted_signer_rejected", "signed_diagnostics", "replay_prevention",
        "durable_idempotent_result", "token_revocation", "replacement_token"]}))


if __name__ == "__main__":
    main()
