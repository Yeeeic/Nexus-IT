from starlette.responses import Response

from backend.app.auth.cookies import set_auth_cookies
from backend.app.auth.session_tokens import issue_session_secrets


def test_set_auth_cookies_hardens_session_and_csrf_cookies() -> None:
    response = Response()
    secrets = issue_session_secrets()

    set_auth_cookies(response, secrets)

    cookies = response.headers.getlist("set-cookie")
    assert len(cookies) == 2
    session_cookie = next(cookie for cookie in cookies if "nexus_session" in cookie)
    csrf_cookie = next(cookie for cookie in cookies if "nexus_csrf" in cookie)

    assert session_cookie.startswith(
        f"__Host-nexus_session={secrets.session_token};"
    )
    assert "HttpOnly" in session_cookie
    assert "Max-Age=3600" in session_cookie
    assert "Path=/" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "Secure" in session_cookie
    assert "Domain=" not in session_cookie

    assert csrf_cookie.startswith(f"__Host-nexus_csrf={secrets.csrf_token};")
    assert "HttpOnly" not in csrf_cookie
    assert "Max-Age=3600" in csrf_cookie
    assert "Path=/" in csrf_cookie
    assert "SameSite=lax" in csrf_cookie
    assert "Secure" in csrf_cookie
    assert "Domain=" not in csrf_cookie
