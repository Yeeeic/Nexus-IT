"""Tests for MetricMaintenanceService (partition creation, downsampling, and retention)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.metrics.maintenance import (
    DAILY_AGGREGATE_RETENTION_DAYS,
    HOURLY_AGGREGATE_RETENTION_DAYS,
    RAW_RETENTION_DAYS,
    MetricMaintenanceWorker,
    MetricMaintenanceService,
)


def test_run_downsampling_executes_rollup_query() -> None:
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 42
    mock_conn.execute.return_value = mock_result
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    service = MetricMaintenanceService(mock_engine)
    org_id = uuid4()

    result = asyncio.run(
        service.run_downsampling(
            organization_id=org_id,
            bucket_seconds=3600,
            older_than_hours=1,
        )
    )

    assert result.buckets_created_or_updated == 42
    assert result.duration_ms >= 0
    assert mock_conn.execute.call_count == 3  # role + tenant context + rollup


def test_apply_retention_policy_executes_purges_and_audit() -> None:
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    result_row = MagicMock()
    result_row.one.return_value = (100, 10, 4, 2)
    mock_conn.execute.side_effect = [None, result_row]
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    service = MetricMaintenanceService(mock_engine)

    assert RAW_RETENTION_DAYS == 14
    assert HOURLY_AGGREGATE_RETENTION_DAYS == 90
    assert DAILY_AGGREGATE_RETENTION_DAYS == 365
    result = asyncio.run(service.apply_retention_policy())

    assert result.raw_samples_deleted == 100
    assert result.hourly_aggregate_rows_deleted == 10
    assert result.daily_aggregate_rows_deleted == 4
    assert result.partitions_dropped == 2
    assert mock_conn.execute.call_count == 2
    query = str(mock_conn.execute.call_args_list[1].args[0])
    assert "run_metric_maintenance" in query
    assert "DROP TABLE" not in query


def test_maintenance_worker_runs_both_rollups_and_retention() -> None:
    organization_id = uuid4()
    metrics_application = MagicMock()
    metrics_application.list_active_organization_ids = AsyncMock(
        return_value=(organization_id,)
    )
    service = MagicMock()

    @asynccontextmanager
    async def acquired_lock():
        yield True

    service.cycle_lock = acquired_lock
    service.run_downsampling = AsyncMock()
    service.apply_retention_policy = AsyncMock()
    worker = MetricMaintenanceWorker(metrics_application, service)

    asyncio.run(worker.run_once())

    assert service.run_downsampling.await_count == 2
    assert service.run_downsampling.await_args_list[0].kwargs == {
        "organization_id": organization_id,
        "bucket_seconds": 3600,
        "older_than_hours": 1,
    }
    assert service.run_downsampling.await_args_list[1].kwargs == {
        "organization_id": organization_id,
        "bucket_seconds": 86400,
        "older_than_hours": 24,
    }
    service.apply_retention_policy.assert_awaited_once_with()


def test_maintenance_worker_skips_cycle_when_another_replica_is_leader() -> None:
    metrics_application = MagicMock()
    metrics_application.list_active_organization_ids = AsyncMock()
    service = MagicMock()
    service.run_downsampling = AsyncMock()
    service.apply_retention_policy = AsyncMock()

    @asynccontextmanager
    async def unavailable_lock():
        yield False

    service.cycle_lock = unavailable_lock
    worker = MetricMaintenanceWorker(metrics_application, service)

    assert asyncio.run(worker.run_once()) is None
    metrics_application.list_active_organization_ids.assert_not_awaited()
    service.run_downsampling.assert_not_awaited()
    service.apply_retention_policy.assert_not_awaited()
