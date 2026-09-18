"""Reusable authentication and CSRF dependencies for private routes."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol, cast

from fastapi import Cookie, Depends, Header, HTTPException, Request, Response

from backend.app.auth.cookies import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    refresh_auth_cookies,
)
from backend.app.auth.session import (
    AuthorizationRejected,
    SessionIdentity,
    SessionRejected,
    SessionUnavailable,
)
from backend.app.auth.session_rate_limit import (
    SessionRequestLimited,
    SessionRequestLimitUnavailable,
    SessionRequestRateLimiter,
)


class SessionApplication(Protocol):
    async def authenticate(
        self,
        session_token: str,
        *,
        require_organization: bool = True,
    ) -> SessionIdentity: ...


def get_session_application(request: Request) -> SessionApplication:
    application = getattr(request.app.state, "session_application", None)
    if application is None:
        raise SessionUnavailable
    return cast(SessionApplication, application)


def get_session_rate_limiter(request: Request) -> SessionRequestRateLimiter:
    limiter = getattr(request.app.state, "session_request_rate_limiter", None)
    if limiter is None:
        raise SessionUnavailable
    return cast(SessionRequestRateLimiter, limiter)


async def require_session(
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
    application: SessionApplication = Depends(get_session_application),
    limiter: SessionRequestRateLimiter = Depends(get_session_rate_limiter),
) -> SessionIdentity:
    if session_token is None:
        raise SessionRejected
    identity = await application.authenticate(
        session_token,
        require_organization=True,
    )
    request.state.identity = identity
    try:
        await limiter.allow(identity.session_id)
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
    return identity


async def require_csrf(
    identity: SessionIdentity = Depends(require_session),
    csrf_cookie: Annotated[
        str | None,
        Cookie(alias=CSRF_COOKIE_NAME),
    ] = None,
    csrf_header: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
) -> SessionIdentity:
    identity.verify_csrf(cookie=csrf_cookie, header=csrf_header)
    return identity


def require_permission(
    permission: str,
    *,
    csrf: bool = False,
) -> Callable[..., Awaitable[SessionIdentity]]:
    identity_dependency = require_csrf if csrf else require_session

    async def dependency(
        identity: SessionIdentity = Depends(identity_dependency),
    ) -> SessionIdentity:
        if permission not in identity.permissions:
            raise AuthorizationRejected
        return identity

    return dependency
