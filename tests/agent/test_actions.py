import json
import hashlib
import base64
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Lock, Thread
from datetime import UTC, datetime
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent.nexus_agent.actions import (
    AgentActionOrder,
    SQLiteActionStore,
    build_signing_payload,
)


ACTION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_ACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ORG_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
DEVICE_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
NONCE = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


def order(action_id: UUID = ACTION_ID) -> AgentActionOrder:
    unsigned = AgentActionOrder(
        action_execution_id=action_id,
        organization_id=ORG_ID,
        device_id=DEVICE_ID,
        nonce=NONCE,
        action_name="flush_dns",
        action_version=1,
        key_version=1,
        issued_at="2026-08-24T18:30:00Z",
        expires_at="2026-08-24T18:35:00Z",
        order_digest="",
        signature="signed",
        parameters_canonical="{}",
    )
    return replace(
        unsigned,
        order_digest=hashlib.sha256(build_signing_payload(unsigned)).hexdigest(),
    )


def test_acceptance_persists_nonce_and_order_in_one_transaction(tmp_path: Path) -> None:
    store = SQLiteActionStore(tmp_path / "actions.sqlite3")

    assert store.accept(order(), expires_at_with_skew=1_777_000_000) is True
    assert store.accept(order(OTHER_ACTION_ID), expires_at_with_skew=1_777_000_000) is False
    assert store.status(ACTION_ID) == "ACCEPTED"
    assert store.status(OTHER_ACTION_ID) is None


def test_two_workers_execute_effect_at_most_once(tmp_path: Path) -> None:
    store = SQLiteActionStore(tmp_path / "actions.sqlite3")
    assert store.accept(order(), expires_at_with_skew=1_777_000_000)
    barrier = Barrier(2)
    lock = Lock()
    effects = 0
    results: list[bool] = []

    def flush_dns(parameters: dict[str, object]) -> tuple[int, str]:
        nonlocal effects
        assert parameters == {}
        with lock:
            effects += 1
        return 0, "ok"

    def worker() -> None:
        barrier.wait()
        result = store.execute_once(ACTION_ID, {"flush_dns": flush_dns})
        with lock:
            results.append(result)

    workers = [Thread(target=worker), Thread(target=worker)]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join()

    assert effects == 1
    assert sorted(results) == [False, True]
    assert store.status(ACTION_ID) == "SUCCEEDED"


def test_recovery_never_reexecutes_previously_claimed_action(tmp_path: Path) -> None:
    store = SQLiteActionStore(tmp_path / "actions.sqlite3")
    assert store.accept(order(), expires_at_with_skew=1_777_000_000)
    assert store.claim(ACTION_ID) is True

    store.reconcile_after_restart(now_epoch=1_776_000_000)

    assert store.status(ACTION_ID) == "UNKNOWN"
    assert store.claim(ACTION_ID) is False


def test_action_order_rejects_noncanonical_or_unknown_action() -> None:
    with pytest.raises(ValueError):
        SQLiteActionStore.validate_order(replace(order(), action_name="run_shell"))

    noncanonical = json.dumps({"b": 1, "a": 2})
    with pytest.raises(ValueError):
        SQLiteActionStore.validate_order(
            replace(order(), parameters_canonical=noncanonical)
        )


def test_verified_acceptance_rejects_unknown_key_and_accepts_ed25519(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    unsigned = order()
    signature = private_key.sign(build_signing_payload(unsigned))
    signed = replace(
        unsigned,
        signature=base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
    )
    store = SQLiteActionStore(tmp_path / "verified.sqlite3")

    with pytest.raises(ValueError, match="desconocida"):
        store.verify_and_accept(
            signed,
            public_keys={},
            now=datetime(2026, 8, 24, 18, 31, tzinfo=UTC),
        )

    assert store.verify_and_accept(
        signed,
        public_keys={1: public_key},
        now=datetime(2026, 8, 24, 18, 31, tzinfo=UTC),
    )
