"""Fail-closed construction and cleanup of authentication infrastructure."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.administration.postgres import PostgresAdministration
from backend.app.auth.application import LoginApplicationService
from backend.app.auth.context import ContextSelectionApplication
from backend.app.auth.logout import LogoutApplication
from backend.app.auth.password_reset import PasswordResetApplication
from backend.app.auth.password_reset_notifier import SmtpPasswordResetNotifier
from backend.app.auth.password_reset_request import (
    PasswordResetRequestApplication,
)
from backend.app.auth.postgres import PostgresLoginRepository
from backend.app.auth.rate_limit import LoginRateLimiter
from backend.app.auth.session import SessionApplicationService
from backend.app.auth.session_rate_limit import SessionRequestRateLimiter
from backend.app.core.config import (
    AppSettings,
    AttachmentSettings,
    DatabaseSettings,
    EmailSettings,
    RedisSettings,
    RemoteActionSettings,
)
from backend.app.core.database import create_database_engine
from backend.app.devices.postgres import (
    PostgresAgentTokenRepository,
    PostgresDeviceService,
)
from backend.app.devices.service import AgentTokenApplication
from backend.app.devices.rate_limit import AgentRequestRateLimiter
from backend.app.metrics.alert_notifier import SmtpAlertNotifier
from backend.app.metrics.maintenance import (
    MetricMaintenanceService,
    MetricMaintenanceWorker,
)
from backend.app.metrics.postgres import PostgresMetricRepository
from backend.app.metrics.rate_limit import MetricIngestRateLimiter
from backend.app.metrics.service import MetricsApplication
from backend.app.metrics.worker import MetricBatchWorker
from backend.app.realtime.hub import RedisRealtimeHub
from backend.app.support.attachments import LocalAttachmentStorage
from backend.app.support.crypto import Ed25519ActionSigner
from backend.app.support.postgres import PostgresSupportRepository
from backend.app.support.service import SupportService
from backend.app.users.postgres import PostgresUserDirectory


@dataclass(slots=True)
class AppRuntime:
    engine: AsyncEngine
    maintenance_engine: AsyncEngine
    redis: Redis
    login_application: LoginApplicationService
    session_application: SessionApplicationService
    session_request_rate_limiter: SessionRequestRateLimiter
    context_application: ContextSelectionApplication
    logout_application: LogoutApplication
    password_reset_application: PasswordResetApplication
    password_reset_request_application: PasswordResetRequestApplication
    user_directory: PostgresUserDirectory
    administration: PostgresAdministration
    device_service: PostgresDeviceService
    agent_token_application: AgentTokenApplication
    agent_request_rate_limiter: AgentRequestRateLimiter
    metrics_application: MetricsApplication
    metric_ingest_rate_limiter: MetricIngestRateLimiter
    realtime_hub: RedisRealtimeHub
    support_application: SupportService
    metric_worker: MetricBatchWorker
    metric_maintenance_worker: MetricMaintenanceWorker

    async def close(self) -> None:
        self.metric_worker.stop()
        self.metric_maintenance_worker.stop()
        await self.redis.aclose()
        await self.maintenance_engine.dispose()
        await self.engine.dispose()


async def create_runtime(environ: Mapping[str, str]) -> AppRuntime:
    app_settings = AppSettings.from_environment(environ)
    database_settings = DatabaseSettings.from_environment(environ)
    maintenance_environment = dict(environ)
    maintenance_environment.update(
        {
            "NEXUS_DATABASE_HOST": environ.get(
                "NEXUS_MAINTENANCE_DATABASE_HOST", database_settings.host
            ),
            "NEXUS_DATABASE_PORT": environ.get(
                "NEXUS_MAINTENANCE_DATABASE_PORT", str(database_settings.port)
            ),
            "NEXUS_DATABASE_NAME": environ.get(
                "NEXUS_MAINTENANCE_DATABASE_NAME", database_settings.name
            ),
            "NEXUS_DATABASE_USER": environ.get("NEXUS_MAINTENANCE_DATABASE_USER"),
            "NEXUS_DATABASE_PASSWORD": environ.get(
                "NEXUS_MAINTENANCE_DATABASE_PASSWORD"
            ),
        }
    )
    maintenance_database_settings = DatabaseSettings.from_environment(
        maintenance_environment
    )
    redis_settings = RedisSettings.from_environment(environ)
    email_settings = EmailSettings.from_environment(environ)
    remote_action_settings = RemoteActionSettings.from_environment(environ)
    attachment_settings = AttachmentSettings.from_environment(environ)

    engine = create_database_engine(database_settings)
    maintenance_engine = create_database_engine(maintenance_database_settings)
    redis = Redis(
        host=redis_settings.host,
        port=redis_settings.port,
        db=redis_settings.database,
        username="default",
        password=redis_settings.password.get_secret_value(),
        protocol=2,
        max_connections=500,
        decode_responses=False,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        async with maintenance_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        await redis.ping()
    except BaseException:
        await redis.aclose()
        await engine.dispose()
        await maintenance_engine.dispose()
        raise

    pepper = app_settings.server_pepper.get_secret_value().encode("utf-8")
    rate_limiter = LoginRateLimiter(
        redis,
        pepper=pepper,
    )
    login_application = LoginApplicationService(
        repository_factory=lambda: PostgresLoginRepository(engine),
        rate_limiter=rate_limiter,
    )
    session_application = SessionApplicationService(
        repository_factory=lambda: PostgresLoginRepository(engine),
        clock=lambda: datetime.now(UTC),
    )
    session_request_rate_limiter = SessionRequestRateLimiter(redis)
    context_application = ContextSelectionApplication(
        repository_factory=lambda: PostgresLoginRepository(engine),
        clock=lambda: datetime.now(UTC),
    )
    logout_application = LogoutApplication(
        repository_factory=lambda: PostgresLoginRepository(engine),
        clock=lambda: datetime.now(UTC),
    )
    password_reset_application = PasswordResetApplication(
        lambda: PostgresLoginRepository(engine),
        pepper=pepper,
        request_guard=rate_limiter,
        clock=lambda: datetime.now(UTC),
    )
    password_reset_request_application = PasswordResetRequestApplication(
        lambda: PostgresLoginRepository(engine),
        pepper=pepper,
        request_guard=rate_limiter,
        notifier=SmtpPasswordResetNotifier(email_settings),
        clock=lambda: datetime.now(UTC),
    )
    user_directory = PostgresUserDirectory(engine)
    administration = PostgresAdministration(engine)
    device_service = PostgresDeviceService(engine, pepper=pepper)
    agent_token_application = AgentTokenApplication(
        lambda: PostgresAgentTokenRepository(engine),
        pepper=pepper,
    )
    agent_request_rate_limiter = AgentRequestRateLimiter(redis, pepper=pepper)
    metrics_application = MetricsApplication(PostgresMetricRepository(engine))
    metric_ingest_rate_limiter = MetricIngestRateLimiter(redis)
    realtime_hub = RedisRealtimeHub(
        redis,
        allowed_origins=app_settings.allowed_origins,
    )
    attachment_storage = LocalAttachmentStorage(
        root=Path(attachment_settings.root_directory)
    )
    support_application = SupportService(
        repository=PostgresSupportRepository(engine),
        signer=Ed25519ActionSigner.from_base64(
            remote_action_settings.private_key.get_secret_value(),
            key_version=remote_action_settings.key_version,
        ),
        attachment_storage=attachment_storage,
        clock=lambda: datetime.now(UTC),
    )
    metric_worker = MetricBatchWorker(
        metrics_application=metrics_application,
        realtime_hub=realtime_hub,
        alert_notifier=SmtpAlertNotifier(email_settings),
        clock=lambda: datetime.now(UTC),
    )
    metric_maintenance_worker = MetricMaintenanceWorker(
        metrics_application,
        MetricMaintenanceService(maintenance_engine),
        clock=lambda: datetime.now(UTC),
    )
    return AppRuntime(
        engine=engine,
        maintenance_engine=maintenance_engine,
        redis=redis,
        login_application=login_application,
        session_application=session_application,
        session_request_rate_limiter=session_request_rate_limiter,
        context_application=context_application,
        logout_application=logout_application,
        password_reset_application=password_reset_application,
        password_reset_request_application=password_reset_request_application,
        user_directory=user_directory,
        administration=administration,
        device_service=device_service,
        agent_token_application=agent_token_application,
        agent_request_rate_limiter=agent_request_rate_limiter,
        metrics_application=metrics_application,
        metric_ingest_rate_limiter=metric_ingest_rate_limiter,
        realtime_hub=realtime_hub,
        support_application=support_application,
        metric_worker=metric_worker,
        metric_maintenance_worker=metric_maintenance_worker,
    )
