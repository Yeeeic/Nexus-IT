import asyncio
from uuid import UUID

import pytest

from backend.app.metrics.rate_limit import (
    MetricIngestRateLimiter,
    MetricRateLimited,
    MetricRateLimitUnavailable,
)


ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
TOKEN_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class Redis:
    def __init__(self, response: list[int] | Exception) -> None:
        self.response = response
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, *arguments: object) -> list[int]:
        self.calls.append(arguments)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_rate_limiter_uses_tenant_and_token_scoped_atomic_key() -> None:
    redis = Redis([1, 500])
    limiter = MetricIngestRateLimiter(redis)

    asyncio.run(limiter.allow(ORG_ID, TOKEN_ID))

    assert redis.calls[0][2] == f"nexus:metrics:ingest:{ORG_ID}:{TOKEN_ID}"


def test_rate_limiter_returns_retry_after_and_fails_closed() -> None:
    with pytest.raises(MetricRateLimited) as limited:
        asyncio.run(MetricIngestRateLimiter(Redis([0, 1_001])).allow(ORG_ID, TOKEN_ID))
    assert limited.value.retry_after_seconds == 2

    with pytest.raises(MetricRateLimitUnavailable):
        asyncio.run(
            MetricIngestRateLimiter(Redis(RuntimeError("redis down"))).allow(
                ORG_ID,
                TOKEN_ID,
            )
        )
