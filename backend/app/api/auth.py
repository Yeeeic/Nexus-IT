"""Versioned HTTP contract for human authentication."""

from typing import Annotated, Protocol, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse

from backend.app.api.dependencies import (
    get_session_application,
    get_session_rate_limiter,
)
from backend.app.auth.cookies import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    clear_auth_cookies,
    refresh_auth_cookies,
    set_auth_cookies,
)
from backend.app.auth.context import (
    ContextSelectionApplication,
    ContextSelectionRejected,
    ContextSelectionResult,
)
from backend.app.auth.logout import LogoutApplication
from backend.app.auth.application import LoginApplicationUnavailable
from backend.app.auth.login import LoginResult
from backend.app.auth.rate_limit import (
    LoginRateLimitUnavailable,
    LoginRequestRateLimited,
)
from backend.app.auth.password_reset import (
    PasswordResetApplication,
    PasswordResetRejected,
    PasswordResetUnavailable,
)
from backend.app.auth.password_reset_request import (
    PasswordResetRequestApplication,
)
from backend.app.auth.schemas import (
    ContextSelectionRequest,
    ContextSelectionResponse,
    LoginOrganization,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    UserMeResponse,
)
from backend.app.auth.session import (
    SessionApplicationService,
    SessionRejected,
    SessionUnavailable,
)
from backend.app.auth.session_rate_limit import (
    SessionRequestLimited,
    SessionRequestLimitUnavailable,
    SessionRequestRateLimiter,
)
from backend.app.auth.service import (
    INVALID_CREDENTIALS_MESSAGE,
    AuthenticationRejected,
)


auth_router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginApplication(Protocol):
    async def login(
        self,
        request: LoginRequest,
        *,
        previous_session_token: str | None,
        user_agent: str | None,
        ip_address: str,
    ) -> LoginResult: ...


def get_login_application(request: Request) -> LoginApplication:
    application = getattr(request.app.state, "login_application", None)
    if application is None:
        raise LoginRateLimitUnavailable
    return cast(LoginApplication, application)


def get_context_application(request: Request) -> ContextSelectionApplication:
    application = getattr(request.app.state, "context_application", None)
    if application is None:
        raise SessionUnavailable
    return cast(ContextSelectionApplication, application)


def get_logout_application(request: Request) -> LogoutApplication:
    application = getattr(request.app.state, "logout_application", None)
    if application is None:
        raise SessionUnavailable
    return cast(LogoutApplication, application)


def get_password_reset_application(request: Request) -> PasswordResetApplication:
    application = getattr(request.app.state, "password_reset_application", None)
    if application is None:
        raise PasswordResetUnavailable
    return cast(PasswordResetApplication, application)


def get_password_reset_request_application(
    request: Request,
) -> PasswordResetRequestApplication:
    application = getattr(
        request.app.state,
        "password_reset_request_application",
        None,
    )
    if application is None:
        raise PasswordResetUnavailable
    return cast(PasswordResetRequestApplication, application)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


@auth_router.post(
    "/login",
    response_model=LoginResponse,
    responses={401: {}, 429: {}, 503: {}},
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    application: LoginApplication = Depends(get_login_application),
) -> LoginResponse | JSONResponse:
    client = request.client
    if client is None:
        return _error_response(
            503,
            "SERVICE_UNAVAILABLE",
            "Servicio temporalmente no disponible",
        )

    try:
        result = await application.login(
            payload,
            previous_session_token=request.cookies.get(SESSION_COOKIE_NAME),
            user_agent=request.headers.get("user-agent"),
            ip_address=client.host,
        )
    except AuthenticationRejected:
        return _error_response(
            401,
            "INVALID_CREDENTIALS",
            INVALID_CREDENTIALS_MESSAGE,
        )
    except LoginRequestRateLimited as error:
        return _error_response(
            429,
            "RATE_LIMITED",
            "Demasiadas solicitudes",
            headers={"Retry-After": str(error.retry_after_seconds)},
        )
    except (LoginRateLimitUnavailable, LoginApplicationUnavailable) as exc:
        import traceback
        print("LOGIN ERROR:", exc, "CAUSE:", exc.__cause__)
        if exc.__cause__:
            traceback.print_exception(exc.__cause__)
        return _error_response(
            503,
            "SERVICE_UNAVAILABLE",
            "Servicio temporalmente no disponible",
        )

    set_auth_cookies(response, result.secrets)
    return LoginResponse(
        status=result.status.value,
        organizations=tuple(
            LoginOrganization(
                id=membership.organization_id,
                name=membership.organization_name,
            )
            for membership in result.organizations
        ),
    )


@auth_router.post(
    "/context",
    response_model=ContextSelectionResponse,
    responses={401: {}, 403: {}, 503: {}},
)
async def select_context(
    payload: ContextSelectionRequest,
    request: Request,
    response: Response,
    session_token: Annotated[
        str | None,
        Cookie(alias=SESSION_COOKIE_NAME),
    ] = None,
    csrf_cookie: Annotated[
        str | None,
        Cookie(alias=CSRF_COOKIE_NAME),
    ] = None,
    csrf_header: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
    application: ContextSelectionApplication = Depends(get_context_application),
) -> ContextSelectionResponse | JSONResponse:
    if session_token is None:
        raise SessionRejected
    client = request.client
    if client is None:
        raise SessionUnavailable
    try:
        result: ContextSelectionResult = await application.select(
            session_token=session_token,
            csrf_cookie=csrf_cookie,
            csrf_header=csrf_header,
            organization_id=payload.organization_id,
            user_agent=request.headers.get("user-agent"),
            ip_address=client.host,
        )
    except ContextSelectionRejected:
        return _error_response(
            403,
            "CONTEXT_NOT_AUTHORIZED",
            "Contexto de organización no autorizado",
        )
    set_auth_cookies(response, result.secrets)
    return ContextSelectionResponse()


@auth_router.post(
    "/logout",
    response_model=LogoutResponse,
    responses={401: {}, 403: {}, 503: {}},
)
async def logout(
    request: Request,
    response: Response,
    session_token: Annotated[
        str | None,
        Cookie(alias=SESSION_COOKIE_NAME),
    ] = None,
    csrf_cookie: Annotated[
        str | None,
        Cookie(alias=CSRF_COOKIE_NAME),
    ] = None,
    csrf_header: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
    application: LogoutApplication = Depends(get_logout_application),
) -> LogoutResponse:
    if session_token is None:
        raise SessionRejected
    client = request.client
    if client is None:
        raise SessionUnavailable
    await application.logout(
        session_token=session_token,
        csrf_cookie=csrf_cookie,
        csrf_header=csrf_header,
        user_agent=request.headers.get("user-agent"),
        ip_address=client.host,
    )
    clear_auth_cookies(response)
    return LogoutResponse()


@auth_router.post(
    "/password-reset/confirm",
    response_model=PasswordResetConfirmResponse,
    responses={400: {}, 429: {}, 503: {}},
)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    application: PasswordResetApplication = Depends(
        get_password_reset_application
    ),
) -> PasswordResetConfirmResponse | JSONResponse:
    client = request.client
    if client is None:
        return _error_response(
            503,
            "SERVICE_UNAVAILABLE",
            "Servicio temporalmente no disponible",
        )
    try:
        await application.consume(
            payload.token.get_secret_value(),
            payload.new_password.get_secret_value(),
            ip_address=client.host,
            user_agent=request.headers.get("user-agent"),
        )
    except LoginRequestRateLimited as error:
        return _error_response(
            429,
            "RATE_LIMITED",
            "Demasiadas solicitudes",
            headers={"Retry-After": str(error.retry_after_seconds)},
        )
    except PasswordResetRejected:
        return _error_response(
            400,
            "INVALID_PASSWORD_RESET",
            "Solicitud de restablecimiento invÃ¡lida o expirada",
        )
    except PasswordResetUnavailable:
        return _error_response(
            503,
            "SERVICE_UNAVAILABLE",
            "Servicio temporalmente no disponible",
        )
    return PasswordResetConfirmResponse()


@auth_router.post(
    "/password-reset/request",
    response_model=PasswordResetRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={429: {}, 503: {}},
)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    application: PasswordResetRequestApplication = Depends(
        get_password_reset_request_application
    ),
) -> PasswordResetRequestResponse | JSONResponse:
    client = request.client
    if client is None:
        return _error_response(
            503,
            "SERVICE_UNAVAILABLE",
            "Servicio temporalmente no disponible",
        )
    try:
        delivery = await application.request(
            payload.email,
            ip_address=client.host,
            user_agent=request.headers.get("user-agent"),
        )
    except LoginRequestRateLimited as error:
        return _error_response(
            429,
            "RATE_LIMITED",
            "Demasiadas solicitudes",
            headers={"Retry-After": str(error.retry_after_seconds)},
        )
    except PasswordResetUnavailable:
        return _error_response(
            503,
            "SERVICE_UNAVAILABLE",
            "Servicio temporalmente no disponible",
        )
    if delivery is not None:
        background_tasks.add_task(application.deliver, delivery)
    return PasswordResetRequestResponse()


@auth_router.get(
    "/me",
    response_model=UserMeResponse,
    responses={401: {}, 429: {}, 503: {}},
)
async def get_current_user_me(
    request: Request,
    response: Response,
    session_token: Annotated[
        str | None,
        Cookie(alias=SESSION_COOKIE_NAME),
    ] = None,
    csrf_cookie: Annotated[
        str | None,
        Cookie(alias=CSRF_COOKIE_NAME),
    ] = None,
    application: SessionApplicationService = Depends(get_session_application),
    limiter: SessionRequestRateLimiter = Depends(get_session_rate_limiter),
) -> UserMeResponse:
    if session_token is None:
        raise SessionRejected
    user_me = await application.get_me(session_token)
    try:
        await limiter.allow(user_me.user_id)
    except SessionRequestLimited as error:
        raise HTTPException(
            status_code=429,
            detail="Demasiadas solicitudes",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from None
    except SessionRequestLimitUnavailable:
        raise SessionUnavailable from None
    refresh_auth_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_cookie,
    )
    return user_me
