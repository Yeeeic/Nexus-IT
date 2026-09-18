"""Anti-enumeration password-reset request orchestration."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from backend.app.audit import AuditEvent
from backend.app.auth.password_reset import (
    PasswordResetRequestGuard,
    PasswordResetToken,
    PasswordResetUnavailable,
)


class PasswordResetIssueRepository(Protocol):
    async def find_active_reset_user_id(self, email: str) -> UUID | None: ...

    async def replace_password_reset_token(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    async def append_audit(self, event: AuditEvent) -> None: ...


class PasswordResetNotifier(Protocol):
    async def send(self, recipient: str, token: str) -> None: ...


RepositoryFactory = Callable[
    [], AbstractAsyncContextManager[PasswordResetIssueRepository]
]


@dataclass(frozen=True, slots=True)
class PasswordResetDelivery:
    recipient: str
    token: str

    def __repr__(self) -> str:
        return (
            "PasswordResetDelivery("
            f"recipient={self.recipient!r}, token=Secret('**********'))"
        )


class PasswordResetRequestApplication:
    def __init__(
        self,
        repository_factory: RepositoryFactory,
        *,
        pepper: bytes,
        request_guard: PasswordResetRequestGuard,
        notifier: PasswordResetNotifier,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if len(pepper) < 32:
            raise ValueError("password reset pepper must contain at least 32 bytes")
        self._repository_factory = repository_factory
        self._pepper = pepper
        self._request_guard = request_guard
        self._notifier = notifier
        self._clock = clock
        self._id_factory = id_factory

    async def request(
        self,
        normalized_email: str,
        *,
        ip_address: str,
        user_agent: str | None,
    ) -> PasswordResetDelivery | None:
        await self._request_guard.preflight(normalized_email, ip_address)
        now = self._clock()
        token = PasswordResetToken.generate(self._pepper)
        try:
            async with self._repository_factory() as repository:
                user_id = await repository.find_active_reset_user_id(
                    normalized_email
                )
                if user_id is None:
                    return None
                await repository.replace_password_reset_token(
                    token_id=token.token_id,
                    user_id=user_id,
                    token_hash=token.secret_hash,
                    created_at=now,
                    expires_at=now + timedelta(minutes=15),
                )
                await repository.append_audit(
                    AuditEvent(
                        id=self._id_factory(),
                        organization_id=None,
                        actor_id=user_id,
                        actor_type="USER",
                        ip_address=ip_address,
                        user_agent=(user_agent or "").strip()[:255] or None,
                        action="AUTH.PASSWORD_RESET_REQUESTED",
                        resource_type="USER",
                        resource_id=user_id,
                        status="SUCCESS",
                        details={},
                    )
                )
        except Exception:
            raise PasswordResetUnavailable from None
        return PasswordResetDelivery(normalized_email, token.value)

    async def deliver(self, delivery: PasswordResetDelivery) -> None:
        # Delivery runs after the uniform HTTP response; errors expose no account state.
        try:
            await self._notifier.send(delivery.recipient, delivery.token)
        except Exception:
            return
