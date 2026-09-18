"""HTTP outcome policy for durable metric batches."""

from __future__ import annotations

import random
import re
import hashlib
import json
from typing import Callable, Mapping, Sequence

from .compat import dataclass, Protocol

from .storage import LocalQueue, StoredBatch


@dataclass(frozen=True, slots=True)
class HttpResult:
    status_code: int
    error_code: str = ""
    error_summary: str = ""
    remote_status: str = ""


class BatchSender(Protocol):
    def send(self, body: Mapping[str, object]) -> HttpResult: ...


@dataclass(frozen=True, slots=True)
class DispatchResult:
    outcome: str
    batch_id: str | None
    child_batch_ids: tuple[str, ...] = ()


class BatchDispatcher:
    def __init__(
        self,
        queue: LocalQueue,
        sender: BatchSender,
        *,
        diagnostic: Callable[[str, Mapping[str, object]], None] | None = None,
        random_value: Callable[[], float] = random.random,
        poll_delay_seconds: int = 30,
    ) -> None:
        self._queue = queue
        self._sender = sender
        self._diagnostic = diagnostic or (lambda _code, _details: None)
        self._random = random_value
        self._poll_delay_seconds = max(1, poll_delay_seconds)

    @staticmethod
    def _body(batch: StoredBatch) -> dict[str, object]:
        samples = list(batch.samples)
        serialized = json.dumps(
            samples,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return {
            "batch_id": batch.batch_id,
            "payload_digest": hashlib.sha256(serialized).hexdigest(),
            "samples": samples,
        }

    @staticmethod
    def _safe_error_code(error_code: str, fallback: str) -> str:
        normalized = error_code.strip().upper()
        return normalized if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", normalized) else fallback

    def dispatch_once(self) -> DispatchResult:
        batch = self._queue.next_batch()
        if batch is None:
            return DispatchResult("EMPTY", None)
        try:
            result = self._sender.send(self._body(batch))
        except (OSError, TimeoutError):
            self._defer(batch)
            return DispatchResult("RETRY", batch.batch_id)

        if result.status_code == 200:
            if result.remote_status in ("", "PROCESSED"):
                self._queue.acknowledge(batch.batch_id)
                return DispatchResult("ACKNOWLEDGED", batch.batch_id)
            if result.remote_status in ("RECEIVED", "PROCESSING"):
                self._queue.defer(batch.batch_id, delay_seconds=self._poll_delay_seconds)
                return DispatchResult("ACCEPTED", batch.batch_id)
            self._queue.defer(batch.batch_id, delay_seconds=self._poll_delay_seconds * 2)
            return DispatchResult("RETAINED", batch.batch_id)

        if result.status_code == 202:
            # HTTP 202 Accepted confirms durable server inbox receipt (status: RECEIVED).
            # The local batch is NOT acknowledged; it must be retained until confirmed PROCESSED.
            self._queue.defer(batch.batch_id, delay_seconds=self._poll_delay_seconds)
            return DispatchResult("ACCEPTED", batch.batch_id)

        if result.status_code == 413:
            return self._handle_413(batch)
        if result.status_code == 422:
            code = self._safe_error_code(result.error_code, "HTTP_422_SCHEMA_REJECTED")
            self._queue.quarantine_batch(
                batch, error_code=code, error_summary=result.error_summary or "schema validation rejected",
            )
            self._diagnostic(
                "BATCH_QUARANTINED_422",
                {"batch_id": batch.batch_id, "error_code": code, "sample_count": len(batch.samples)},
            )
            return DispatchResult("QUARANTINED", batch.batch_id)
        if result.status_code == 0 or result.status_code == 429 or result.status_code >= 500:
            self._defer(batch)
            return DispatchResult("RETRY", batch.batch_id)

        code = self._safe_error_code(result.error_code, f"HTTP_{result.status_code}_TERMINAL")
        self._queue.quarantine_batch(
            batch, error_code=code, error_summary=result.error_summary or "terminal client rejection",
        )
        self._diagnostic("BATCH_TERMINAL_REJECTION", {"batch_id": batch.batch_id, "error_code": code})
        return DispatchResult("QUARANTINED", batch.batch_id)

    def reconcile_status(self, batch_id: str, remote_status: str) -> str:
        """Reconcile local queue state according to remote server batch status."""
        normalized = remote_status.strip().upper()
        if normalized == "PROCESSED":
            acknowledged = self._queue.acknowledge(batch_id)
            return "ACKNOWLEDGED" if acknowledged else "NOT_FOUND"
        if normalized in ("RECEIVED", "PROCESSING"):
            self._queue.defer(batch_id, delay_seconds=self._poll_delay_seconds)
            return "RETAINED"
        if normalized == "DLQ":
            self._queue.defer(batch_id, delay_seconds=self._poll_delay_seconds * 2)
            return "RETAINED_DLQ"
        if normalized == "AWAITING_REUPLOAD":
            self._queue.defer(batch_id, delay_seconds=self._poll_delay_seconds)
            return "AWAITING_REUPLOAD"
        if normalized == "DLQ_EXHAUSTED":
            self._queue.defer(batch_id, delay_seconds=self._poll_delay_seconds * 4)
            return "RETAINED_EXHAUSTED"
        if normalized == "PURGE_LOCAL":
            acknowledged = self._queue.acknowledge(batch_id)
            return "PURGED" if acknowledged else "NOT_FOUND"
        return "UNKNOWN"

    def reconcile_statuses(self, statuses: Mapping[str, str]) -> dict[str, str]:
        """Reconcile multiple batch statuses from a batch status query response."""
        return {
            batch_id: self.reconcile_status(batch_id, status)
            for batch_id, status in statuses.items()
        }

    def reupload_batch(self, batch_id: str) -> DispatchResult:
        """Re-upload a stored batch to the server for an authorized retry."""
        batch = self._queue.get_batch(batch_id)
        if batch is None:
            return DispatchResult("NOT_FOUND", batch_id)
        try:
            if hasattr(self._sender, "reupload"):
                result = self._sender.reupload(batch_id, self._body(batch))  # type: ignore[union-attr]
            else:
                result = self._sender.send(self._body(batch))
        except (OSError, TimeoutError):
            self._defer(batch)
            return DispatchResult("RETRY", batch_id)

        if result.status_code in (200, 202):
            self._queue.defer(batch_id, delay_seconds=self._poll_delay_seconds)
            return DispatchResult("ACCEPTED", batch_id)
        if result.status_code in (0, 429) or result.status_code >= 500:
            self._defer(batch)
            return DispatchResult("RETRY", batch_id)
        return DispatchResult("REJECTED", batch_id)

    def _handle_413(self, batch: StoredBatch) -> DispatchResult:
        if len(batch.samples) == 1:
            self._queue.quarantine_sample(batch, reason="HTTP_413_SINGLE_SAMPLE_TOO_LARGE")
            self._diagnostic(
                "SAMPLE_QUARANTINED_413", {"batch_id": batch.batch_id, "split_depth": batch.split_depth},
            )
            return DispatchResult("SAMPLE_QUARANTINED", batch.batch_id)
        if batch.split_depth >= 3:
            self._queue.quarantine_batch(
                batch,
                error_code="HTTP_413_SPLIT_LIMIT",
                error_summary="batch remains too large after three split levels",
            )
            self._diagnostic(
                "BATCH_SPLIT_LIMIT_REACHED", {"batch_id": batch.batch_id, "split_depth": batch.split_depth},
            )
            return DispatchResult("QUARANTINED", batch.batch_id)
        children = self._queue.split(batch)
        return DispatchResult("SPLIT", batch.batch_id, children)

    def _defer(self, batch: StoredBatch) -> None:
        base = min(30 * (2 ** min(batch.attempts, 6)), 1_800)
        jitter = int(base * 0.25 * self._random())
        self._queue.defer(batch.batch_id, delay_seconds=base + jitter)
