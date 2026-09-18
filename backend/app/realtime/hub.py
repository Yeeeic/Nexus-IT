"""Redis-backed tenant WebSocket fanout with bounded client buffers."""

import asyncio
from collections import deque
import json
from typing import Any, Protocol
from uuid import UUID


class BoundedClientBuffer:
    def __init__(self, *, capacity: int = 100) -> None:
        if capacity < 1 or capacity > 100:
            raise ValueError("buffer capacity must be between 1 and 100")
        self._capacity = capacity
        self._items: deque[tuple[bool, dict[str, Any]]] = deque()
        self._condition = asyncio.Condition()

    @property
    def size(self) -> int:
        return len(self._items)

    async def put(self, message: dict[str, Any], *, critical: bool) -> bool:
        async with self._condition:
            if len(self._items) >= self._capacity:
                if not critical:
                    return False
                for index, (queued_critical, _queued_message) in enumerate(
                    self._items
                ):
                    if not queued_critical:
                        del self._items[index]
                        break
                else:
                    return False
            self._items.append((critical, message))
            self._condition.notify()
            return True

    async def get(self) -> dict[str, Any]:
        async with self._condition:
            await self._condition.wait_for(lambda: bool(self._items))
            return self._items.popleft()[1]


class RedisPubSub(Protocol):
    async def subscribe(self, channel: str) -> None: ...
    async def unsubscribe(self, channel: str) -> None: ...
    async def get_message(
        self, *, ignore_subscribe_messages: bool, timeout: float
    ) -> dict[str, Any] | None: ...
    async def aclose(self) -> None: ...


class RedisClient(Protocol):
    def pubsub(self) -> RedisPubSub: ...
    async def publish(self, channel: str, message: str) -> Any: ...


class RealtimeSocket(Protocol):
    async def send_json(self, data: object) -> None: ...
    async def receive_text(self) -> str: ...
    async def close(self, code: int = 1000) -> None: ...


class RedisRealtimeHub:
    def __init__(
        self,
        redis: RedisClient,
        *,
        allowed_origins: tuple[str, ...],
    ) -> None:
        self._redis = redis
        self._allowed_origins = frozenset(allowed_origins)

    def accepts_origin(self, origin: str | None) -> bool:
        return origin is not None and origin in self._allowed_origins

    async def publish(self, organization_id: UUID, event: dict[str, Any]) -> None:
        channel = f"nexus:telemetry:{organization_id}"
        payload = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        if hasattr(self._redis, "publish"):
            await self._redis.publish(channel, payload)

    @staticmethod
    def _event(data: object) -> tuple[dict[str, Any], bool] | None:
        if isinstance(data, bytes):
            if len(data) > 65536:
                return None
            try:
                data = data.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if not isinstance(data, str) or len(data) > 65536:
            return None
        try:
            event = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(event, dict):
            return None
        event_type = event.get("type")
        if event_type not in {"telemetry", "alert", "device_status"}:
            return None
        event.pop("organization_id", None)
        return event, event_type == "alert"

    async def serve(self, websocket: RealtimeSocket, organization_id: UUID) -> None:
        channel = f"nexus:telemetry:{organization_id}"
        pubsub = self._redis.pubsub()
        buffer = BoundedClientBuffer(capacity=100)
        await pubsub.subscribe(channel)
        await websocket.send_json({"type": "ready"})

        async def receive_redis() -> None:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if not message or message.get("type") != "message":
                    await asyncio.sleep(0)
                    continue
                parsed = self._event(message.get("data"))
                if parsed is None:
                    continue
                event, critical = parsed
                accepted = await buffer.put(event, critical=critical)
                if critical and not accepted:
                    await websocket.close(code=1013)
                    return

        async def send_client() -> None:
            while True:
                await websocket.send_json(await buffer.get())

        async def receive_client() -> None:
            while True:
                raw = await websocket.receive_text()
                if len(raw) > 1024:
                    await websocket.close(code=1008)
                    return
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.close(code=1008)
                    return
                if message != {"type": "ping"}:
                    await websocket.close(code=1008)
                    return
                await buffer.put({"type": "pong"}, critical=True)

        tasks = {
            asyncio.create_task(receive_redis()),
            asyncio.create_task(send_client()),
            asyncio.create_task(receive_client()),
        }
        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass
