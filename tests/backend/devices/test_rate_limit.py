import asyncio

import pytest

from backend.app.devices.rate_limit import (
    AgentRequestLimited,
    AgentRequestLimitUnavailable,
    AgentRequestRateLimiter,
)


class Redis:
    def __init__(self, response: list[int] | Exception) -> None:
        self.response = response
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, *arguments: object) -> list[int]:
        self.calls.append(arguments)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_agent_limit_never_places_raw_token_in_redis_key() -> None:
    redis = Redis([1, 60])
    limiter = AgentRequestRateLimiter(redis, pepper=b"p" * 32)

    asyncio.run(limiter.preflight("raw-agent-token", "127.0.0.1"))

    key = str(redis.calls[0][2])
    assert key.startswith("nexus:agent:auth:")
    assert "raw-agent-token" not in key


def test_agent_limit_returns_retry_after_and_fails_closed() -> None:
    with pytest.raises(AgentRequestLimited) as limited:
        asyncio.run(
            AgentRequestRateLimiter(Redis([0, 23]), pepper=b"p" * 32).preflight(
                "token",
                "127.0.0.1",
            )
        )
    assert limited.value.retry_after_seconds == 23

    with pytest.raises(AgentRequestLimitUnavailable):
        asyncio.run(
            AgentRequestRateLimiter(
                Redis(RuntimeError("redis down")),
                pepper=b"p" * 32,
            ).preflight("token", "127.0.0.1")
        )
