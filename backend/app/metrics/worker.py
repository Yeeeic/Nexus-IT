"""Supervised multi-tenant asynchronous metric worker and alert pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any
from uuid import UUID

from backend.app.metrics.alert_notifier import SmtpAlertNotifier
from backend.app.metrics.service import AlertSummary, MetricsApplication
from backend.app.realtime.hub import RedisRealtimeHub

logger = logging.getLogger("nexus.metrics.worker")


@dataclass(frozen=True, slots=True)
class WorkerCycleStats:
    started_at: datetime
    completed_at: datetime
    tenants_scanned: int
    batches_processed: int
    alerts_evaluated: int
    duration_ms: float


class MetricBatchWorker:
    """Supervised worker that processes ingested metric batches across active tenants.

    Maintains strict multi-tenant isolation by delegating all batch retrieval
    and state transitions to tenant-scoped transactions with Row-Level Security.
    """

    def __init__(
        self,
        metrics_application: MetricsApplication,
        *,
        realtime_hub: RedisRealtimeHub | None = None,
        alert_notifier: SmtpAlertNotifier | None = None,
        notification_recipients: Sequence[str] = (),
        poll_interval_seconds: float = 1.0,
        max_batches_per_tenant_per_cycle: int = 10,
        error_backoff_seconds: float = 5.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._metrics_application = metrics_application
        self._realtime_hub = realtime_hub
        self._alert_notifier = alert_notifier
        self._notification_recipients = tuple(notification_recipients)
        self._poll_interval = max(0.1, poll_interval_seconds)
        self._max_batches_per_tenant = max(1, max_batches_per_tenant_per_cycle)
        self._error_backoff = max(1.0, error_backoff_seconds)
        self._clock = clock
        self._stop_event = asyncio.Event()
        self._is_running = False
        self._last_stats: WorkerCycleStats | None = None
        self._total_batches_processed = 0
        self._total_errors = 0

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def last_stats(self) -> WorkerCycleStats | None:
        return self._last_stats

    @property
    def total_batches_processed(self) -> int:
        return self._total_batches_processed

    async def run_once(self) -> WorkerCycleStats:
        """Executes a single processing cycle across all active tenants."""
        start = self._clock()
        tenants = await self._metrics_application.list_active_organization_ids()
        batches_count = 0
        alerts_count = 0

        for org_id in tenants:
            if self._stop_event.is_set():
                break
            # Process up to max_batches for this organization
            for _ in range(self._max_batches_per_tenant):
                receipt = await self._metrics_application.process_next_batch(org_id)
                if receipt is None:
                    break
                batches_count += 1
                self._total_batches_processed += 1

            # Evaluate alerts for this organization
            alerts = await self._metrics_application.evaluate_alerts(
                org_id,
                now=self._clock(),
            )
            alerts_count += len(alerts)

            # Fanout alerts to realtime hub and email notifier
            for alert in alerts:
                if self._realtime_hub is not None:
                    try:
                        await self._realtime_hub.publish(
                            org_id,
                            {
                                "type": "alert",
                                "id": str(alert.id),
                                "device_id": str(alert.device_id),
                                "alert_rule_id": (
                                    str(alert.alert_rule_id)
                                    if alert.alert_rule_id
                                    else None
                                ),
                                "severity": alert.severity,
                                "status": alert.status,
                                "message": alert.message,
                                "triggered_at": alert.triggered_at.isoformat(),
                                "resolved_at": (
                                    alert.resolved_at.isoformat()
                                    if alert.resolved_at
                                    else None
                                ),
                            },
                        )
                    except Exception as pub_err:
                        logger.warning(
                            "Error al publicar alerta en hub realtime: %s",
                            pub_err,
                        )

                if alert.status == "OPEN" and self._alert_notifier is not None:
                    try:
                        await self._alert_notifier.notify(
                            self._notification_recipients,
                            alert,
                        )
                    except Exception as notif_err:
                        logger.warning(
                            "Error al enviar notificación de alerta: %s",
                            notif_err,
                        )

        end = self._clock()
        duration_ms = max(0.0, (end - start).total_seconds() * 1000.0)
        stats = WorkerCycleStats(
            started_at=start,
            completed_at=end,
            tenants_scanned=len(tenants),
            batches_processed=batches_count,
            alerts_evaluated=alerts_count,
            duration_ms=duration_ms,
        )
        self._last_stats = stats
        return stats

    async def run_forever(self) -> None:
        """Main supervised loop."""
        self._is_running = True
        self._stop_event.clear()
        logger.info("Iniciando worker de métricas supervisado")
        try:
            while not self._stop_event.is_set():
                try:
                    stats = await self.run_once()
                    if stats.batches_processed == 0 and not self._stop_event.is_set():
                        try:
                            await asyncio.wait_for(
                                self._stop_event.wait(),
                                timeout=self._poll_interval,
                            )
                        except asyncio.TimeoutError:
                            pass
                except asyncio.CancelledError:
                    break
                except Exception as error:
                    self._total_errors += 1
                    logger.error(
                        "Error no manejado en ciclo del worker de métricas: %s",
                        error,
                        exc_info=True,
                    )
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=self._error_backoff,
                        )
                    except asyncio.TimeoutError:
                        pass
        finally:
            self._is_running = False
            logger.info("Worker de métricas detenido limpiamente")

    def stop(self) -> None:
        """Signals the worker to stop gracefully."""
        self._stop_event.set()

    def health_status(self) -> dict[str, Any]:
        """Provides a safe health dictionary for diagnostics/observability."""
        return {
            "is_running": self._is_running,
            "total_batches_processed": self._total_batches_processed,
            "total_errors": self._total_errors,
            "last_cycle": (
                {
                    "tenants_scanned": self._last_stats.tenants_scanned,
                    "batches_processed": self._last_stats.batches_processed,
                    "alerts_evaluated": self._last_stats.alerts_evaluated,
                    "duration_ms": round(self._last_stats.duration_ms, 2),
                    "completed_at": self._last_stats.completed_at.isoformat(),
                }
                if self._last_stats
                else None
            ),
        }
