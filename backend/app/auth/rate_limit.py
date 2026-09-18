"""Atomic, privacy-preserving Redis limits for human login."""

from dataclasses import dataclass
import hashlib
import hmac
import ipaddress
from typing import Protocol


_PREFLIGHT_SCRIPT = """
local ip_attempts = redis.call('INCR', KEYS[1])
if ip_attempts == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
if ip_attempts > tonumber(ARGV[1]) then
  local ip_ttl = redis.call('TTL', KEYS[1])
  return {1, math.max(ip_ttl, 1)}
end

local account_ttl = redis.call('TTL', KEYS[2])
local pair_ttl = redis.call('TTL', KEYS[3])
if account_ttl > 0 or pair_ttl > 0 then
  return {2, math.max(account_ttl, pair_ttl)}
end
return {0, 0}
"""

_FAILURE_SCRIPT = """
local account_failures = redis.call('INCR', KEYS[1])
if account_failures == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
if account_failures >= tonumber(ARGV[1]) then
  redis.call('SET', KEYS[2], '1', 'EX', ARGV[3])
  redis.call('DEL', KEYS[1])
end

local pair_failures = redis.call('INCR', KEYS[3])
if pair_failures == 1 then
  redis.call('EXPIRE', KEYS[3], ARGV[5])
end
if pair_failures >= tonumber(ARGV[4]) then
  redis.call('SET', KEYS[4], '1', 'EX', ARGV[6])
  redis.call('DEL', KEYS[3])
end
return {math.max(account_failures, pair_failures), 0}
"""

_SUCCESS_SCRIPT = """
redis.call('DEL', KEYS[1], KEYS[2])
return {1, 0}
"""


class AsyncRedis(Protocol):
    async def eval(
        self,
        script: str,
        number_of_keys: int,
        *keys_and_args: object,
    ) -> list[int]: ...


class LoginRateLimitUnavailable(Exception):
    def __init__(self) -> None:
        super().__init__("Protección de acceso no disponible")


class LoginRequestRateLimited(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__("Demasiadas solicitudes")


@dataclass(frozen=True, slots=True)
class LoginPreflight:
    credentials_blocked: bool
    retry_after_seconds: int


@dataclass(frozen=True, slots=True)
class LoginFailure:
    delay_seconds: float


class LoginRateLimiter:
    IP_LIMIT = 20
    IP_WINDOW_SECONDS = 60
    ACCOUNT_FAILURE_LIMIT = 5
    ACCOUNT_WINDOW_SECONDS = 15 * 60
    ACCOUNT_LOCK_SECONDS = 15 * 60
    PAIR_FAILURE_LIMIT = 5
    PAIR_WINDOW_SECONDS = 5 * 60
    PAIR_LOCK_SECONDS = 15 * 60
    FAILURE_DELAYS = (0.2, 0.5, 1.0, 2.0)

    def __init__(self, redis: AsyncRedis, *, pepper: bytes) -> None:
        if len(pepper) < 32:
            raise ValueError("rate-limit pepper must contain at least 32 bytes")
        self._redis = redis
        self._pepper = pepper

    def _digest(self, namespace: str, value: str) -> str:
        payload = f"{namespace}:{value}".encode("utf-8")
        return hmac.new(self._pepper, payload, hashlib.sha256).hexdigest()

    def _keys(self, email: str, ip_address: str) -> tuple[str, str, str, str]:
        normalized_email = email.strip().lower()
        normalized_ip = str(ipaddress.ip_address(ip_address))
        account = self._digest("account", normalized_email)
        source = self._digest("ip", normalized_ip)
        pair = self._digest("pair", f"{normalized_ip}:{normalized_email}")
        return (
            f"nexus:login:ip:attempts:{source}",
            f"nexus:login:account:lock:{account}",
            f"nexus:login:pair:lock:{pair}",
            account,
        )

    async def _eval(
        self,
        script: str,
        keys: tuple[str, ...],
        *arguments: int,
    ) -> tuple[int, int]:
        try:
            response = await self._redis.eval(
                script,
                len(keys),
                *keys,
                *arguments,
            )
            if len(response) != 2:
                raise ValueError("unexpected Redis script response")
            return int(response[0]), int(response[1])
        except Exception:
            raise LoginRateLimitUnavailable from None

    async def preflight(self, email: str, ip_address: str) -> LoginPreflight:
        ip_key, account_lock, pair_lock, _ = self._keys(email, ip_address)
        status, retry_after = await self._eval(
            _PREFLIGHT_SCRIPT,
            (ip_key, account_lock, pair_lock),
            self.IP_LIMIT,
            self.IP_WINDOW_SECONDS,
        )
        if status == 1:
            raise LoginRequestRateLimited(retry_after)
        if status not in (0, 2):
            raise LoginRateLimitUnavailable
        return LoginPreflight(
            credentials_blocked=status == 2,
            retry_after_seconds=max(0, retry_after),
        )

    async def record_failure(
        self,
        email: str,
        ip_address: str,
    ) -> LoginFailure:
        _, account_lock, pair_lock, account = self._keys(email, ip_address)
        pair = pair_lock.rsplit(":", maxsplit=1)[-1]
        failure_count, _ = await self._eval(
            _FAILURE_SCRIPT,
            (
                f"nexus:login:account:failures:{account}",
                account_lock,
                f"nexus:login:pair:failures:{pair}",
                pair_lock,
            ),
            self.ACCOUNT_FAILURE_LIMIT,
            self.ACCOUNT_WINDOW_SECONDS,
            self.ACCOUNT_LOCK_SECONDS,
            self.PAIR_FAILURE_LIMIT,
            self.PAIR_WINDOW_SECONDS,
            self.PAIR_LOCK_SECONDS,
        )
        delay_index = min(max(failure_count, 1), len(self.FAILURE_DELAYS)) - 1
        return LoginFailure(delay_seconds=self.FAILURE_DELAYS[delay_index])

    async def record_success(self, email: str, ip_address: str) -> None:
        _, _, pair_lock, account = self._keys(email, ip_address)
        pair = pair_lock.rsplit(":", maxsplit=1)[-1]
        await self._eval(
            _SUCCESS_SCRIPT,
            (
                f"nexus:login:account:failures:{account}",
                f"nexus:login:pair:failures:{pair}",
            ),
        )
