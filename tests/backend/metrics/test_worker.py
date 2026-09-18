"""Unit and integration tests for MetricBatchWorker and SmtpAlertNotifier."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from email.message import EmailMessage
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from backend.app.core.config import EmailSettings
from backend.app.metrics.alert_notifier import SmtpAlertNotifier
from backend.app.metrics.service import AlertSummary, BatchReceipt, MetricsApplication
from backend.app.metrics.worker import MetricBatchWorker
from backend.app.realtime.hub import RedisRealtimeHub


class MockSmtpTransport:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.started_tls = False
        self.logged_in = False
        self.sent_messages: list[EmailMessage] = []

    def __enter__(self) -> MockSmtpTransport:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def starttls(self, *, context: object) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in = True

    def send_message(self, message: EmailMessage) -> None:
        self.sent_messages.append(message)


def test_smtp_alert_notifier_sends_email_via_tls() -> None:
    settings = EmailSettings(
        host="smtp.example.com",
        port=587,
        username="nexus@example.com",
        password="a-secure-smtp-password-16-bytes",
        sender="nexus@example.com",
        password_reset_url="https://app.example.com/reset",
    )
    mock_transport = MockSmtpTransport()
    notifier = SmtpAlertNotifier(
        settings,
        transport_factory=lambda *args, **kwargs: mock_transport,
    )

    alert = AlertSummary(
        id=uuid4(),
        device_id=uuid4(),
        alert_rule_id=uuid4(),
        severity="CRITICAL",
        status="OPEN",
        message="CPU usage exceeded 90%",
        triggered_at=datetime.now(UTC),
        resolved_at=None,
    )

    asyncio.run(notifier.notify(["admin@example.com"], alert))

    assert mock_transport.started_tls is True
    assert mock_transport.logged_in is True
    assert len(mock_transport.sent_messages) == 1
    msg = mock_transport.sent_messages[0]
    assert msg["To"] == "admin@example.com"
    assert "CRITICAL" in msg["Subject"]


def test_metric_batch_worker_processes_batches_and_evaluates_alerts() -> None:
    org1 = uuid4()
    org2 = uuid4()
    app = AsyncMock(spec=MetricsApplication)
    app.list_active_organization_ids.return_value = (org1, org2)

    batch1 = BatchReceipt(batch_id=uuid4(), status="PROCESSED", duplicate=False)
    # Return batch1 once for org1, then None; None for org2
    app.process_next_batch.side_effect = [batch1, None, None]

    alert1 = AlertSummary(
        id=uuid4(),
        device_id=uuid4(),
        alert_rule_id=uuid4(),
        severity="WARNING",
        status="OPEN",
        message="Memory high",
        triggered_at=datetime.now(UTC),
        resolved_at=None,
    )
    app.evaluate_alerts.side_effect = [[alert1], []]

    realtime_hub = AsyncMock(spec=RedisRealtimeHub)
    mock_notifier = AsyncMock(spec=SmtpAlertNotifier)

    fixed_now = datetime(2026, 8, 25, 5, 0, 0, tzinfo=UTC)
    worker = MetricBatchWorker(
        metrics_application=app,
        realtime_hub=realtime_hub,
        alert_notifier=mock_notifier,
        notification_recipients=["admin@example.com"],
        poll_interval_seconds=0.1,
        clock=lambda: fixed_now,
    )

    stats = asyncio.run(worker.run_once())

    assert stats.tenants_scanned == 2
    assert stats.batches_processed == 1
    assert stats.alerts_evaluated == 1

    # Verify multi-tenant isolation: process_next_batch called per organization
    assert app.process_next_batch.call_count == 3
    app.evaluate_alerts.assert_any_call(org1, now=stats.started_at)
    app.evaluate_alerts.assert_any_call(org2, now=stats.started_at)

    # Verify realtime broadcast & email notification
    realtime_hub.publish.assert_called_once()
    assert realtime_hub.publish.call_args[0][0] == org1
    assert realtime_hub.publish.call_args[0][1]["type"] == "alert"
    mock_notifier.notify.assert_called_once_with(("admin@example.com",), alert1)


def test_metric_batch_worker_health_and_graceful_stop() -> None:
    app = AsyncMock(spec=MetricsApplication)
    app.list_active_organization_ids.return_value = ()
    worker = MetricBatchWorker(
        metrics_application=app,
        poll_interval_seconds=0.05,
    )

    health = worker.health_status()
    assert health["is_running"] is False
    assert health["total_batches_processed"] == 0

    async def run_and_stop():
        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.1)
        assert worker.is_running is True
        worker.stop()
        await task

    asyncio.run(run_and_stop())
    assert worker.is_running is False
