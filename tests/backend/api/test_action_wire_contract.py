"""The real agent must accept the exact JSON emitted by the API."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent.nexus_agent.actions import AgentActionOrder, SQLiteActionStore
from backend.app.api.support import _action_response
from backend.app.support.crypto import Ed25519ActionSigner
from backend.app.support.service import ActionCommand, RequestTrace, build_action_signing_payload


def test_serialized_action_verifies_and_rejects_replay(tmp_path):
    key = Ed25519PrivateKey.generate()
    signer = Ed25519ActionSigner(key.private_bytes_raw(), key_version=1)
    now = datetime.now(timezone.utc).replace(microsecond=123456)
    command = ActionCommand(
        organization_id=uuid4(), id=uuid4(), device_id=uuid4(),
        action_name="collect_extended_diagnostics", requested_by=uuid4(),
        nonce=uuid4(), key_version=1, issued_at=now,
        expires_at=now + timedelta(minutes=5), signature=None,
        parameters={"include_logs": False, "max_log_lines": 100},
        parameters_canonical='{"include_logs":false,"max_log_lines":100}',
        status="DISPATCHED", trace=RequestTrace(None, None),
    )
    command = replace(command, signature=signer.sign(build_action_signing_payload(command)))
    wire = _action_response(command).model_dump(mode="json")
    order = AgentActionOrder(
        action_execution_id=UUID(wire["id"]), organization_id=UUID(wire["organization_id"]),
        device_id=UUID(wire["device_id"]), nonce=UUID(wire["nonce"]),
        action_name=wire["action_name"], action_version=wire["action_version"],
        key_version=wire["key_version"], issued_at=wire["issued_at"],
        expires_at=wire["expires_at"], signature=wire["signature"],
        order_digest=wire["order_digest"], parameters_canonical=wire["parameters_canonical"],
    )
    store = SQLiteActionStore(tmp_path / "actions.db")
    keys = {1: key.public_key().public_bytes_raw()}
    assert store.verify_and_accept(order, public_keys=keys, now=now)
    assert not store.verify_and_accept(order, public_keys=keys, now=now)
