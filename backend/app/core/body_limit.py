"""ASGI request-body limits enforced before framework parsing."""

import re
from collections.abc import Awaitable, Callable
from typing import Any


Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
App = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


_LIMITS = (
    (
        re.compile(
            r"^/api/v1/devices/[0-9a-fA-F-]{36}/metrics/batches(?:/[0-9a-fA-F-]{36}/reupload)?$"
        ),
        512 * 1024,
    ),
    (
        re.compile(r"^/api/v1/devices/[0-9a-fA-F-]{36}/inventory$"),
        2 * 1024 * 1024,
    ),
)


class RequestBodyLimitMiddleware:
    def __init__(self, app: App) -> None:
        self._app = app

    @staticmethod
    def _limit(path: str) -> int | None:
        for pattern, limit in _LIMITS:
            if pattern.fullmatch(path):
                return limit
        return None

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"error":{"code":"PAYLOAD_TOO_LARGE","message":"Payload demasiado grande"}}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        limit = self._limit(str(scope.get("path", "")))
        if limit is None:
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers", ()))
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) < 0 or int(declared) > limit:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return

        messages: list[dict[str, Any]] = []
        size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    await self._reject(send)
                    return
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                break

        async def replay() -> dict[str, Any]:
            if messages:
                return messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        await self._app(scope, replay, send)
