"""Daily metric rollups and retention under a least-privilege database boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.metrics.service import MetricsApplication


logger = logging.getLogger("nexus.metrics.maintenance")

RAW_RETENTION_DAYS = 14
HOURLY_AGGREGATE_RETENTION_DAYS = 90
DAILY_AGGREGATE_RETENTION_DAYS = 365
HOURLY_BUCKET_SECONDS = 3600
DAILY_BUCKET_SECONDS = 86400


@dataclass(frozen=True, slots=True)
class DownsamplingResult:
    buckets_created_or_updated: int
    duration_ms: float


@dataclass(frozen=True, slots=True)
class RetentionResult:
    raw_samples_deleted: int
    hourly_aggregate_rows_deleted: int
    daily_aggregate_rows_deleted: int
    partitions_dropped: int
    duration_ms: float

    @property
    def aggregate_rows_deleted(self) -> int:
        return self.hourly_aggregate_rows_deleted + self.daily_aggregate_rows_deleted


class MetricMaintenanceService:
    """Runs tenant rollups and invokes narrowly scoped database maintenance."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def cycle_lock(self) -> AsyncIterator[bool]:
        """Elect one maintenance leader while keeping its DB session open."""
        async with self._engine.connect() as connection:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(1314084173, 1129270604)")
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(1314084173, 1129270604)")
                    )

    async def run_downsampling(
        self,
        *,
        organization_id: UUID,
        bucket_seconds: int,
        older_than_hours: int,
        now: datetime | None = None,
    ) -> DownsamplingResult:
        """Roll raw telemetry into one supported UTC interval for one tenant."""
        if bucket_seconds not in {HOURLY_BUCKET_SECONDS, DAILY_BUCKET_SECONDS}:
            raise ValueError("unsupported metric aggregate interval")
        current_time = datetime.now(UTC) if now is None else now
        cutoff = current_time - timedelta(hours=older_than_hours)
        started_at = datetime.now(UTC)
        query = text(
            """
            INSERT INTO public.metric_aggregates (
                organization_id, device_id, metric_name, bucket_start,
                bucket_interval_seconds, sample_count, min_value,
                max_value, avg_value
            )
            SELECT
                organization_id,
                device_id,
                metric_name,
                to_timestamp(
                    floor(extract(epoch FROM recorded_at) / :bucket_seconds)
                    * :bucket_seconds
                ) AS bucket_start,
                :bucket_seconds AS bucket_interval_seconds,
                count(*) AS sample_count,
                min(metric_value) AS min_value,
                max(metric_value) AS max_value,
                avg(metric_value) AS avg_value
            FROM public.metric_samples
            WHERE recorded_at <= :cutoff
              AND organization_id = :organization_id
            GROUP BY
                organization_id,
                device_id,
                metric_name,
                to_timestamp(
                    floor(extract(epoch FROM recorded_at) / :bucket_seconds)
                    * :bucket_seconds
                )
            ON CONFLICT (
                organization_id, device_id, metric_name,
                bucket_interval_seconds, bucket_start
            )
            DO UPDATE SET
                sample_count = EXCLUDED.sample_count,
                min_value = EXCLUDED.min_value,
                max_value = EXCLUDED.max_value,
                avg_value = EXCLUDED.avg_value
            """
        )
        async with self._engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE nexus_app_user"))
            await connection.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                {"org_id": str(organization_id)},
            )
            result = await connection.execute(
                query,
                {
                    "bucket_seconds": bucket_seconds,
                    "cutoff": cutoff,
                    "organization_id": organization_id,
                },
            )

        duration_ms = (datetime.now(UTC) - started_at).total_seconds() * 1000.0
        return DownsamplingResult(
            buckets_created_or_updated=result.rowcount or 0,
            duration_ms=duration_ms,
        )

    async def apply_retention_policy(self) -> RetentionResult:
        """Apply fixed RF-10 retention through a constrained DB function.

        Runtime receives EXECUTE only. Partition DDL, cross-tenant deletion, and
        valid per-organization audit records stay inside one database transaction.
        """
        started_at = datetime.now(UTC)
        async with self._engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE nexus_metrics_maintenance"))
            result = await connection.execute(
                text(
                    """
                    SELECT
                        raw_samples_deleted,
                        hourly_aggregates_deleted,
                        daily_aggregates_deleted,
                        partitions_dropped
                    FROM public.run_metric_maintenance()
                    """
                )
            )
            raw, hourly, daily, partitions = result.one()

        duration_ms = (datetime.now(UTC) - started_at).total_seconds() * 1000.0
        return RetentionResult(
            raw_samples_deleted=int(raw),
            hourly_aggregate_rows_deleted=int(hourly),
            daily_aggregate_rows_deleted=int(daily),
            partitions_dropped=int(partitions),
            duration_ms=duration_ms,
        )


class MetricMaintenanceWorker:
    """Schedules one maintenance cycle immediately and then once per day."""

    def __init__(
        self,
        metrics_application: MetricsApplication,
        service: MetricMaintenanceService,
        *,
        interval_seconds: float = 86400.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._metrics_application = metrics_application
        self._service = service
        self._interval_seconds = max(60.0, interval_seconds)
        self._clock = clock
        self._stop_event = asyncio.Event()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def run_once(self) -> RetentionResult | None:
        """Create hourly/daily rollups for active tenants, then enforce retention."""
        async with self._service.cycle_lock() as acquired:
            if not acquired:
                return None
            organizations = await self._metrics_application.list_active_organization_ids()
            for organization_id in organizations:
                await self._service.run_downsampling(
                    organization_id=organization_id,
                    bucket_seconds=HOURLY_BUCKET_SECONDS,
                    older_than_hours=1,
                )
                await self._service.run_downsampling(
                    organization_id=organization_id,
                    bucket_seconds=DAILY_BUCKET_SECONDS,
                    older_than_hours=24,
                )
            return await self._service.apply_retention_policy()

    async def run_forever(self) -> None:
        self._is_running = True
        self._stop_event.clear()
        logger.info("Iniciando mantenimiento diario de métricas")
        try:
            while not self._stop_event.is_set():
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Falló ciclo de mantenimiento de métricas")
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self._is_running = False
            logger.info("Mantenimiento diario de métricas detenido")

    def stop(self) -> None:
        self._stop_event.set()
