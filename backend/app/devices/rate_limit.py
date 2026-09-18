"""Privacy-preserving Redis guard for machine-token authentication."""

import hashlib
import hmac
import ipaddress
from typing import Protocol


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


class AgentRequestLimited(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(retry_after_seconds, 1)


class AgentRequestLimitUnavailable(Exception):
    pass


class AgentRequestRateLimiter:
    LIMIT = 30
    WINDOW_SECONDS = 60

    def __init__(self, redis: AsyncRedis, *, pepper: bytes) -> None:
        if len(pepper) < 32:
            raise ValueError("rate-limit pepper must contain at least 32 bytes")
        self._redis = redis
        self._pepper = pepper

    def _key(self, token: str, ip_address: str) -> str:
        try:
            normalized_ip = str(ipaddress.ip_address(ip_address))
        except ValueError:
            normalized_ip = "invalid"
        digest = hmac.new(
            self._pepper,
            f"{normalized_ip}:{token}".encode("utf-8", errors="replace"),
            hashlib.sha256,
        ).hexdigest()
        return f"nexus:agent:auth:{digest}"

    async def preflight(self, token: str, ip_address: str) -> None:
        try:
            response = await self._redis.eval(
                _LIMIT_SCRIPT,
                1,
                self._key(token, ip_address),
                self.LIMIT,
                self.WINDOW_SECONDS,
            )
            if len(response) != 2:
                raise ValueError("unexpected Redis script response")
            allowed, retry_after = int(response[0]), int(response[1])
        except Exception:
            raise AgentRequestLimitUnavailable from None
        if allowed == 0:
            raise AgentRequestLimited(retry_after)
