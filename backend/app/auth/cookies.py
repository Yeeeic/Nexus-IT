"""Secure browser cookie emission for authenticated sessions."""

from starlette.responses import Response

from backend.app.auth.session_tokens import SessionSecrets


SESSION_COOKIE_NAME = "__Host-nexus_session"
CSRF_COOKIE_NAME = "__Host-nexus_csrf"
SESSION_IDLE_SECONDS = 60 * 60


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_IDLE_SECONDS,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=SESSION_IDLE_SECONDS,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )


def set_auth_cookies(response: Response, secrets: SessionSecrets) -> None:
    _set_session_cookie(response, secrets.session_token)
    # JavaScript must echo this token in a header; server validates its stored hash.
    _set_csrf_cookie(response, secrets.csrf_token)


def refresh_auth_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_token: str | None,
) -> None:
    """Refresh browser expiry after the server renewed the same opaque session."""
    _set_session_cookie(response, session_token)
    if csrf_token is not None:
        _set_csrf_cookie(response, csrf_token)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )
