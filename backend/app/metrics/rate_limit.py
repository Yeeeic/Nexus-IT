"""Atomic per-agent metric ingestion limit."""

from typing import Protocol
from uuid import UUID


_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
local ttl = redis.call('PTTL', KEYS[1])
if count > tonumber(ARGV[1]) then
  return {0, math.max(ttl, 1)}
end
return {1, math.max(ttl, 1)}
"""


class AsyncRedis(Protocol):
    async def eval(
        self,
        script: str,
        number_of_keys: int,
        *keys_and_args: object,
    ) -> list[int]: ...


class MetricRateLimitUnavailable(Exception):
    pass


class MetricRateLimited(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(retry_after_seconds, 1)


class MetricIngestRateLimiter:
    LIMIT = 2
    WINDOW_MILLISECONDS = 1_000

    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    async def allow(self, organization_id: UUID, token_id: UUID) -> None:
        key = f"nexus:metrics:ingest:{organization_id}:{token_id}"
        try:
            response = await self._redis.eval(
                _LIMIT_SCRIPT,
                1,
                key,
                self.LIMIT,
                self.WINDOW_MILLISECONDS,
            )
            if len(response) != 2:
                raise ValueError("unexpected Redis script response")
            allowed, retry_after_ms = int(response[0]), int(response[1])
        except Exception:
            raise MetricRateLimitUnavailable from None
        if allowed == 0:
            retry_after_seconds = (retry_after_ms + 999) // 1_000
            raise MetricRateLimited(retry_after_seconds)
