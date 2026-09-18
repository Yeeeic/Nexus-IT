"""Atomic request budget for authenticated web sessions."""

from typing import Protocol
from uuid import UUID


_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local ttl = redis.call('TTL', KEYS[1])
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


class SessionRequestLimited(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(retry_after_seconds, 1)


class SessionRequestLimitUnavailable(Exception):
    pass


class SessionRequestRateLimiter:
    LIMIT = 60
    WINDOW_SECONDS = 60

    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    async def allow(self, session_id: UUID) -> None:
        try:
            response = await self._redis.eval(
                _LIMIT_SCRIPT,
                1,
                f"nexus:session:requests:{session_id}",
                self.LIMIT,
                self.WINDOW_SECONDS,
            )
            if len(response) != 2:
                raise ValueError("unexpected Redis script response")
            allowed, retry_after = int(response[0]), int(response[1])
        except Exception:
            raise SessionRequestLimitUnavailable from None
        if allowed == 0:
            raise SessionRequestLimited(retry_after)
