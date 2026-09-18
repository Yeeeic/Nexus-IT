import asyncio

import pytest

from backend.app.auth.rate_limit import (
    LoginRateLimiter,
    LoginRateLimitUnavailable,
    LoginRequestRateLimited,
)


class FakeRedis:
    def __init__(self, responses: list[list[int]] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[tuple[str, int, tuple[object, ...]]] = []

    async def eval(
        self,
        script: str,
        number_of_keys: int,
        *values: object,
    ) -> list[int]:
        self.calls.append((script, number_of_keys, values))
        return self.responses.pop(0)


def test_preflight_uses_pseudonymous_keys_and_allows_request() -> None:
    redis = FakeRedis([[0, 0]])
    limiter = LoginRateLimiter(redis, pepper=b"p" * 32)

    result = asyncio.run(
        limiter.preflight("User@Example.test", "192.0.2.10")
    )

    assert result.credentials_blocked is False
    _, key_count, values = redis.calls[0]
    keys = tuple(str(value) for value in values[:key_count])
    assert key_count == 3
    assert all("user@example.test" not in key for key in keys)
    assert all("192.0.2.10" not in key for key in keys)


def test_preflight_preserves_uniform_credential_block_response() -> None:
    limiter = LoginRateLimiter(FakeRedis([[2, 840]]), pepper=b"p" * 32)

    result = asyncio.run(
        limiter.preflight("user@example.test", "192.0.2.10")
    )

    assert result.credentials_blocked is True
    assert result.retry_after_seconds == 840


def test_preflight_raises_only_for_global_ip_limit() -> None:
    limiter = LoginRateLimiter(FakeRedis([[1, 42]]), pepper=b"p" * 32)

    with pytest.raises(LoginRequestRateLimited) as error:
        asyncio.run(
            limiter.preflight("user@example.test", "192.0.2.10")
        )

    assert error.value.retry_after_seconds == 42
    assert "user@example.test" not in repr(error.value)
    assert "192.0.2.10" not in repr(error.value)


@pytest.mark.parametrize(
    ("failure_count", "expected_delay"),
    [(1, 0.2), (2, 0.5), (3, 1.0), (4, 2.0), (50, 2.0)],
)
def test_failure_delay_is_progressive_and_bounded(
    failure_count: int,
    expected_delay: float,
) -> None:
    limiter = LoginRateLimiter(
        FakeRedis([[failure_count, 0]]),
        pepper=b"p" * 32,
    )

    result = asyncio.run(
        limiter.record_failure("user@example.test", "192.0.2.10")
    )

    assert result.delay_seconds == expected_delay


def test_success_clears_failure_counters_without_clearing_active_locks() -> None:
    redis = FakeRedis([[1, 0]])
    limiter = LoginRateLimiter(redis, pepper=b"p" * 32)

    asyncio.run(limiter.record_success("user@example.test", "192.0.2.10"))

    _, key_count, values = redis.calls[0]
    assert key_count == 2
    assert all(":lock:" not in str(value) for value in values[:key_count])


def test_redis_failure_fails_closed_without_leaking_details() -> None:
    class BrokenRedis:
        async def eval(self, *_args: object) -> list[int]:
            raise RuntimeError("redis://user:secret@internal")

    limiter = LoginRateLimiter(BrokenRedis(), pepper=b"p" * 32)

    with pytest.raises(LoginRateLimitUnavailable) as error:
        asyncio.run(
            limiter.preflight("user@example.test", "192.0.2.10")
        )

    assert "secret" not in str(error.value)
    assert "internal" not in repr(error.value)
