from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.metrics.schemas import MetricBatchInput, MetricSampleInput


BATCH_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _digest(samples: list[dict[str, object]]) -> str:
    payload = json.dumps(
        samples,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def test_batch_normalizes_samples_for_stable_digest() -> None:
    recorded_at = datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc)
    sample = MetricSampleInput(
        metric_name="cpu.usage_percent",
        metric_value=42.5,
        recorded_at=recorded_at,
        labels={"core": "0"},
    )
    canonical = [
        {
            "labels": {"core": "0"},
            "metric_name": "cpu.usage_percent",
            "metric_value": "42.5",
            "recorded_at": "2026-08-24T12:30:00Z",
        }
    ]

    batch = MetricBatchInput(
        batch_id=BATCH_ID,
        payload_digest=_digest(canonical),
        samples=[sample],
    )

    assert batch.canonical_samples() == canonical
    assert batch.computed_digest() == _digest(canonical)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_sample_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValidationError):
        MetricSampleInput(
            metric_name="cpu.usage_percent",
            metric_value=value,
            recorded_at=datetime.now(timezone.utc),
        )

def test_batch_rejects_unknown_fields_and_naive_timestamps() -> None:
    with pytest.raises(ValidationError):
        MetricBatchInput.model_validate(
            {
                "batch_id": str(BATCH_ID),
                "payload_digest": "0" * 64,
                "samples": [
                    {
                        "metric_name": "cpu.usage_percent",
                        "metric_value": 5,
                        "recorded_at": "2026-08-24T12:30:00",
                        "organization_id": str(UUID(int=1)),
                    }
                ],
            }
        )
