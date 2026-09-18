import asyncio
from uuid import UUID

import pytest

from backend.app.auth.session_rate_limit import (
    SessionRequestLimited,
    SessionRequestLimitUnavailable,
    SessionRequestRateLimiter,
)


SESSION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class Redis:
    def __init__(self, response: list[int] | Exception) -> None:
        self.response = response
        self.arguments: tuple[object, ...] | None = None

    async def eval(self, *arguments: object) -> list[int]:
        self.arguments = arguments
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_session_request_limit_is_60_per_minute() -> None:
    redis = Redis([1, 60])
    asyncio.run(SessionRequestRateLimiter(redis).allow(SESSION_ID))

    assert redis.arguments is not None
    assert redis.arguments[-2:] == (60, 60)

    with pytest.raises(SessionRequestLimited) as limited:
        asyncio.run(SessionRequestRateLimiter(Redis([0, 42])).allow(SESSION_ID))
    assert limited.value.retry_after_seconds == 42


def test_session_request_limit_fails_closed() -> None:
    with pytest.raises(SessionRequestLimitUnavailable):
        asyncio.run(
            SessionRequestRateLimiter(Redis(RuntimeError("down"))).allow(SESSION_ID)
        )
