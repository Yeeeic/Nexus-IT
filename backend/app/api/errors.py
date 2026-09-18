"""Safe public errors with correlation IDs and sanitized security logging."""

import json
import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.auth.session import (
    AuthorizationRejected,
    CsrfRejected,
    SessionRejected,
    SessionUnavailable,
)


logger = logging.getLogger("nexus.security")


def _error_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return str(value or uuid4())


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "error_id": _error_id(request),
            }
        },
    )


def _security_log(
    request: Request,
    *,
    event: str,
    status_code: int,
    denied_fields: list[str] | None = None,
) -> None:
    identity = getattr(request.state, "identity", None)
    record = {
        "event": event,
        "status": status_code,
        "error_id": _error_id(request),
        "method": request.method,
        "path": request.url.path,
        "organization_id": str(getattr(identity, "organization_id", "")) or None,
        "actor_id": str(getattr(identity, "user_id", "")) or None,
        "ip_address": request.client.host if request.client else None,
        "user_agent": (request.headers.get("user-agent") or "")[:255] or None,
        "denied_fields": denied_fields or [],
    }
    logger.warning(json.dumps(record, sort_keys=True, separators=(",", ":")))


async def request_validation_error_handler(
    request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    denied_fields = sorted(
        {
            str(item)
            for detail in error.errors()
            for item in detail.get("loc", ())[1:]
            if isinstance(item, (str, int))
        }
    )[:25]
    _security_log(
        request,
        event="REQUEST_VALIDATION_REJECTED",
        status_code=422,
        denied_fields=denied_fields,
    )
    return _response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Solicitud inválida",
    )


async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
    messages = {
        400: ("BAD_REQUEST", "Solicitud inválida"),
        401: ("AUTHENTICATION_REQUIRED", "Autenticación requerida"),
        403: ("FORBIDDEN", "Acceso denegado"),
        404: ("NOT_FOUND", "Recurso no encontrado"),
        409: ("CONFLICT", "Conflicto de estado"),
        413: ("PAYLOAD_TOO_LARGE", "Payload demasiado grande"),
        429: ("RATE_LIMITED", "Demasiadas solicitudes"),
        503: ("SERVICE_UNAVAILABLE", "Servicio temporalmente no disponible"),
    }
    code, fallback = messages.get(
        error.status_code,
        ("REQUEST_FAILED", "No fue posible completar la solicitud"),
    )
    if error.status_code in {403, 413, 422, 429}:
        _security_log(request, event=code, status_code=error.status_code)
    message = error.detail if isinstance(error.detail, str) else fallback
    return _response(
        request,
        status_code=error.status_code,
        code=code,
        message=message,
        headers=error.headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)

    async def session_rejected(request: Request, _error: Exception) -> JSONResponse:
        return _response(
            request,
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message="Autenticación requerida",
        )

    async def csrf_rejected(request: Request, _error: Exception) -> JSONResponse:
        _security_log(request, event="CSRF_REJECTED", status_code=403)
        return _response(
            request,
            status_code=403,
            code="CSRF_REJECTED",
            message="Solicitud no autorizada",
        )

    async def unavailable(request: Request, _error: Exception) -> JSONResponse:
        return _response(
            request,
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="Servicio temporalmente no disponible",
        )

    async def authorization_rejected(
        request: Request, _error: Exception
    ) -> JSONResponse:
        _security_log(request, event="AUTHORIZATION_REJECTED", status_code=403)
        return _response(
            request,
            status_code=403,
            code="FORBIDDEN",
            message="Acceso denegado",
        )

    app.add_exception_handler(SessionRejected, session_rejected)
    app.add_exception_handler(CsrfRejected, csrf_rejected)
    app.add_exception_handler(SessionUnavailable, unavailable)
    app.add_exception_handler(AuthorizationRejected, authorization_rejected)
