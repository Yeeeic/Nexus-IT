import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
import json
import logging
import os
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from backend.app.api.auth import auth_router
from backend.app.api.administration import administration_router
from backend.app.api.devices import devices_router
from backend.app.api.errors import install_error_handlers
from backend.app.api.metrics import metrics_router
from backend.app.api.realtime import realtime_router
from backend.app.api.support import install_support_error_handlers, support_router
from backend.app.api.users import users_router
from backend.app.core.runtime import AppRuntime, create_runtime
from backend.app.core.config import parse_allowed_origins
from backend.app.core.body_limit import RequestBodyLimitMiddleware


RuntimeLoader = Callable[[Mapping[str, str]], Awaitable[AppRuntime]]
logger = logging.getLogger("nexus.http")
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self' wss:; frame-ancestors 'none';"
    ),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def create_app(
    runtime_loader: RuntimeLoader = create_runtime,
    *,
    allowed_origins: tuple[str, ...] | None = None,
    enforce_https: bool | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        runtime = await runtime_loader(os.environ)
        application.state.login_application = runtime.login_application
        application.state.session_application = runtime.session_application
        application.state.session_request_rate_limiter = (
            runtime.session_request_rate_limiter
        )
        application.state.context_application = runtime.context_application
        application.state.logout_application = runtime.logout_application
        application.state.password_reset_application = (
            runtime.password_reset_application
        )
        application.state.password_reset_request_application = (
            runtime.password_reset_request_application
        )
        application.state.user_directory = runtime.user_directory
        application.state.administration = runtime.administration
        application.state.device_service = runtime.device_service
        application.state.agent_token_application = runtime.agent_token_application
        application.state.agent_request_rate_limiter = (
            runtime.agent_request_rate_limiter
        )
        application.state.metric_agent_authenticator = (
            runtime.agent_token_application
        )
        application.state.metrics_application = runtime.metrics_application
        application.state.metric_ingest_rate_limiter = (
            runtime.metric_ingest_rate_limiter
        )
        application.state.realtime_hub = runtime.realtime_hub
        application.state.support_application = runtime.support_application

        worker_tasks = (
            asyncio.create_task(runtime.metric_worker.run_forever()),
            asyncio.create_task(runtime.metric_maintenance_worker.run_forever()),
        )
        try:
            yield
        finally:
            runtime.metric_worker.stop()
            runtime.metric_maintenance_worker.stop()
            for task in worker_tasks:
                task.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            await runtime.close()

    application = FastAPI(
        title="NEXUS IT API",
        version="0.1.0",
        lifespan=lifespan,
    )
    configured_origins = (
        allowed_origins
        if allowed_origins is not None
        else parse_allowed_origins(os.environ.get("NEXUS_ALLOWED_ORIGINS"))
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
        max_age=600,
    )
    application.add_middleware(RequestBodyLimitMiddleware)
    should_enforce_https = (
        enforce_https
        if enforce_https is not None
        else os.environ.get("NEXUS_ENV", "development")
        not in {"development", "test"}
    )
    if should_enforce_https:
        application.add_middleware(HTTPSRedirectMiddleware)

    @application.middleware("http")
    async def add_security_headers(request, call_next):  # type: ignore[no-untyped-def]
        request_id = str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                json.dumps(
                    {
                        "event": "HTTP_REQUEST_FAILED",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            raise
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        response.headers["X-Request-ID"] = request_id
        identity = getattr(request.state, "identity", None)
        logger.info(
            json.dumps(
                {
                    "event": "HTTP_REQUEST_COMPLETED",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "organization_id": str(
                        getattr(identity, "organization_id", "")
                    )
                    or None,
                    "actor_id": str(getattr(identity, "user_id", "")) or None,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return response

    install_error_handlers(application)
    install_support_error_handlers(application)
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(administration_router, prefix="/api/v1")
    application.include_router(users_router, prefix="/api/v1")
    application.include_router(devices_router, prefix="/api/v1")
    application.include_router(metrics_router, prefix="/api/v1")
    application.include_router(realtime_router, prefix="/api/v1")
    application.include_router(support_router, prefix="/api/v1")

    @application.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        """Return minimal liveness information without internal details."""
        return {"status": "ok"}

    return application


app = create_app()
