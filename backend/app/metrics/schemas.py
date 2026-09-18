"""Closed boundary schemas for untrusted agent telemetry."""

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_BATCH_SAMPLES = 2_000
MAX_LABELS = 16
_LABEL_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")


def _canonical_decimal(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", ""} else rendered


class MetricSampleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            pattern=r"^[a-z][a-z0-9_.-]{0,99}$",
        ),
    ]
    metric_value: Annotated[
        Decimal,
        Field(allow_inf_nan=False, max_digits=14, decimal_places=4),
    ]
    recorded_at: datetime
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("recorded_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must include timezone")
        return value.astimezone(timezone.utc)

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_LABELS:
            raise ValueError("too many labels")
        for key, item in value.items():
            if not _LABEL_NAME.fullmatch(key) or len(item) > 128:
                raise ValueError("invalid label")
        return value

    def canonical_value(self) -> dict[str, object]:
        return {
            "labels": dict(sorted(self.labels.items())),
            "metric_name": self.metric_name,
            "metric_value": _canonical_decimal(self.metric_value),
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
        }


class MetricBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    payload_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    samples: Annotated[
        tuple[MetricSampleInput, ...],
        Field(min_length=1, max_length=MAX_BATCH_SAMPLES),
    ]

    def canonical_samples(self) -> list[dict[str, object]]:
        return [sample.canonical_value() for sample in self.samples]

    def computed_digest(self) -> str:
        serialized = json.dumps(
            self.canonical_samples(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return sha256(serialized).hexdigest()


class MetricReuploadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    samples: Annotated[
        tuple[MetricSampleInput, ...],
        Field(min_length=1, max_length=MAX_BATCH_SAMPLES),
    ]

    def canonical_samples(self) -> list[dict[str, object]]:
        return [sample.canonical_value() for sample in self.samples]

    def computed_digest(self) -> str:
        serialized = json.dumps(
            self.canonical_samples(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return sha256(serialized).hexdigest()


class BatchStatusQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=50)]

    @field_validator("batch_ids")
    @classmethod
    def reject_duplicate_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("batch_ids must be unique")
        return value


class BatchRetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(min_length=10, max_length=255)]

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not 10 <= len(normalized) <= 255:
            raise ValueError("reason must contain 10 to 255 characters")
        return normalized


class BatchDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["PURGE_LOCAL", "RETAIN"]
    reason: Annotated[str, Field(min_length=10, max_length=255)]

    @field_validator("reason")
    @classmethod
    def normalize_decision_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not 10 <= len(normalized) <= 255:
            raise ValueError("reason must contain 10 to 255 characters")
        return normalized


ComparisonOperator = Literal["GT", "GTE", "LT", "LTE", "EQ"]
AlertSeverity = Literal["INFO", "WARNING", "CRITICAL"]


class AlertRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=150)]
    metric_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            pattern=r"^[a-z][a-z0-9_.-]{0,99}$",
        ),
    ]
    operator: ComparisonOperator
    threshold_value: Annotated[
        Decimal,
        Field(allow_inf_nan=False, max_digits=14, decimal_places=4),
    ]
    duration_seconds: Annotated[int, Field(ge=0, le=86_400)]
    severity: AlertSeverity

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized
