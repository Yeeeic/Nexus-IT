from __future__ import annotations

from pathlib import Path
from typing import Mapping
import re

from agent.nexus_agent.dispatcher import BatchDispatcher, HttpResult
from agent.nexus_agent.storage import LocalQueue


class TestProtector:
    def protect(self, plaintext: bytes) -> bytes:
        return b"protected" + plaintext[::-1]

    def unprotect(self, ciphertext: bytes) -> bytes:
        return ciphertext.removeprefix(b"protected")[::-1]


class Sender:
    def __init__(self, *results: HttpResult) -> None:
        self.results = list(results)
        self.bodies: list[Mapping[str, object]] = []

    def send(self, body: Mapping[str, object]) -> HttpResult:
        self.bodies.append(body)
        return self.results.pop(0)


def queue(tmp_path: Path, *, clock=lambda: 1_000.0) -> LocalQueue:
    return LocalQueue(
        tmp_path / "agent.db",
        protector=TestProtector(),
        clock=clock,
        enforce_physical_quota=False,
    )


def test_202_retains_batch_in_queue_until_confirmed_processed(tmp_path: Path) -> None:
    now = [1_000.0]
    local = queue(tmp_path, clock=lambda: now[0])
    identifier = local.enqueue([{"cpu": 10}, {"cpu": 12}])
    sender = Sender(HttpResult(202))
    dispatcher = BatchDispatcher(local, sender, poll_delay_seconds=30)

    result = dispatcher.dispatch_once()

    assert result.outcome == "ACCEPTED"
    assert result.batch_id == identifier
    # The batch MUST remain in local queue after HTTP 202
    assert local.counts()["queued"] == 1
    assert local.get_batch(identifier) is not None

    # Status query shows still processing -> retains in queue
    assert dispatcher.reconcile_status(identifier, "PROCESSING") == "RETAINED"
    assert local.counts()["queued"] == 1

    # Status query confirms PROCESSED -> removed safely from queue
    assert dispatcher.reconcile_status(identifier, "PROCESSED") == "ACKNOWLEDGED"
    assert local.counts()["queued"] == 0
    assert re.fullmatch(r"[0-9a-f]{64}", str(sender.bodies[0]["payload_digest"]))
    assert local.get_batch(identifier) is None


def test_200_processed_immediately_acknowledges(tmp_path: Path) -> None:
    local = queue(tmp_path)
    identifier = local.enqueue([{"ram": 40}])
    sender = Sender(HttpResult(200, remote_status="PROCESSED"))
    dispatcher = BatchDispatcher(local, sender)

    result = dispatcher.dispatch_once()

    assert result.outcome == "ACKNOWLEDGED"
    assert result.batch_id == identifier
    assert local.counts()["queued"] == 0


def test_reconcile_statuses_preserves_dlq_and_awaiting_reupload(tmp_path: Path) -> None:
    local = queue(tmp_path)
    b1 = local.enqueue([{"metric": 1}])
    b2 = local.enqueue([{"metric": 2}])
    b3 = local.enqueue([{"metric": 3}])
    b4 = local.enqueue([{"metric": 4}])
    dispatcher = BatchDispatcher(local, Sender())

    outcomes = dispatcher.reconcile_statuses({
        b1: "DLQ",
        b2: "AWAITING_REUPLOAD",
        b3: "DLQ_EXHAUSTED",
        b4: "PROCESSED",
    })

    assert outcomes[b1] == "RETAINED_DLQ"
    assert outcomes[b2] == "AWAITING_REUPLOAD"
    assert outcomes[b3] == "RETAINED_EXHAUSTED"
    assert outcomes[b4] == "ACKNOWLEDGED"
    # b1, b2, b3 retained; b4 acknowledged
    assert local.counts()["queued"] == 3
    assert local.get_batch(b4) is None
    assert local.get_batch(b1) is not None

    # Administrative decision PURGE_LOCAL purges exhausted batch
    assert dispatcher.reconcile_status(b3, "PURGE_LOCAL") == "PURGED"
    assert local.counts()["queued"] == 2


def test_reupload_batch_sends_payload_and_retains_until_processed(tmp_path: Path) -> None:
    local = queue(tmp_path)
    identifier = local.enqueue([{"reupload_data": True}])
    sender = Sender(HttpResult(202))
    dispatcher = BatchDispatcher(local, sender)

    result = dispatcher.reupload_batch(identifier)

    assert result.outcome == "ACCEPTED"
    assert len(sender.bodies) == 1
    assert sender.bodies[0]["batch_id"] == identifier
    assert local.counts()["queued"] == 1


def test_413_splits_symmetrically_and_preserves_parent_trace(tmp_path: Path) -> None:
    local = queue(tmp_path)
    original = local.enqueue([{"n": number} for number in range(4)])
    sender = Sender(HttpResult(413), HttpResult(200), HttpResult(200))
    dispatcher = BatchDispatcher(local, sender)

    split = dispatcher.dispatch_once()

    assert split.outcome == "SPLIT"
    assert len(split.child_batch_ids) == 2
    first = local.next_batch()
    assert first is not None
    assert first.parent_batch_id == original
    assert first.split_depth == 1
    assert len(first.samples) == 2
    assert dispatcher.dispatch_once().outcome == "ACKNOWLEDGED"
    assert dispatcher.dispatch_once().outcome == "ACKNOWLEDGED"
    assert local.counts()["queued"] == 0


def test_single_oversized_sample_moves_to_terminal_quarantine(tmp_path: Path) -> None:
    local = queue(tmp_path)
    identifier = local.enqueue([{"huge": "x" * 100}])
    events: list[str] = []
    dispatcher = BatchDispatcher(
        local,
        Sender(HttpResult(413)),
        diagnostic=lambda code, _details: events.append(code),
    )

    result = dispatcher.dispatch_once()

    assert result.outcome == "SAMPLE_QUARANTINED"
    assert result.batch_id == identifier
    assert local.counts()["queued"] == 0
    assert local.counts()["sample_quarantine"] == 1
    assert events == ["SAMPLE_QUARANTINED_413"]


def test_413_never_splits_beyond_three_levels(tmp_path: Path) -> None:
    local = queue(tmp_path)
    local.enqueue([{"n": 1}, {"n": 2}], split_depth=3)
    dispatcher = BatchDispatcher(local, Sender(HttpResult(413)))

    result = dispatcher.dispatch_once()

    assert result.outcome == "QUARANTINED"
    assert local.counts()["queued"] == 0
    assert local.counts()["batch_quarantine"] == 1


def test_422_is_quarantined_once_and_not_retried(tmp_path: Path) -> None:
    local = queue(tmp_path)
    identifier = local.enqueue([{"invalid": True}])
    sender = Sender(HttpResult(422, "secret=do-not-log", " unknown field   secret "))
    events: list[tuple[str, Mapping[str, object]]] = []
    dispatcher = BatchDispatcher(local, sender, diagnostic=lambda code, details: events.append((code, details)))

    first = dispatcher.dispatch_once()
    second = dispatcher.dispatch_once()

    assert first.outcome == "QUARANTINED"
    assert first.batch_id == identifier
    assert second.outcome == "EMPTY"
    assert len(sender.bodies) == 1
    assert events[0][0] == "BATCH_QUARANTINED_422"
    assert events[0][1]["error_code"] == "HTTP_422_SCHEMA_REJECTED"


def test_network_and_server_failures_are_deferred_with_bounded_backoff(tmp_path: Path) -> None:
    now = [10_000.0]
    local = queue(tmp_path, clock=lambda: now[0])
    identifier = local.enqueue([{"cpu": 5}])
    dispatcher = BatchDispatcher(local, Sender(HttpResult(503)), random_value=lambda: 0.0)

    assert dispatcher.dispatch_once().outcome == "RETRY"
    assert local.next_batch() is None
    now[0] += 30
    pending = local.next_batch()
    assert pending is not None
    assert pending.batch_id == identifier
    assert pending.attempts == 1
