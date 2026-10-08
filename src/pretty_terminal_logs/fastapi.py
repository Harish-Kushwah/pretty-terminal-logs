"""Optional ASGI request-logging middleware (works with FastAPI, Starlette or any ASGI app).

It is plain ASGI, so importing it does not import FastAPI; install the ``fastapi`` extra only
if you are using FastAPI itself::

    from pretty_terminal_logs.fastapi import LoggingMiddleware

    app.add_middleware(LoggingMiddleware)
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from .context import get_context_logger, log_context

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class LoggingMiddleware:
    """Logs one entry per HTTP request (method, path, status, duration) and sets the
    ``request_id`` context for everything logged while handling the request.

    The request id is taken from the ``X-Request-ID`` header or generated, and is echoed
    back in the response header.
    """

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        logger_name: str = "pretty_terminal_logs.access",
        module: str = "api",
        header: str = "x-request-id",
    ) -> None:
        self.app = app
        self.header = header.lower().encode("latin-1")
        self.logger = get_context_logger(logger_name, module=module)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        request_id = (headers.get(self.header) or b"").decode("latin-1") or uuid.uuid4().hex[:12]
        status = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (self.header, request_id.encode("latin-1")),
                ]
            await send(message)

        with log_context(request_id=request_id):
            description = f"{scope['method']} {scope['path']}"
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                self._log(logging.ERROR, description, 500, started, exc_info=True)
                raise
            level = (
                logging.ERROR
                if status >= 500
                else logging.WARNING
                if status >= 400
                else logging.INFO
            )
            self._log(level, description, status, started)

    def _log(self, level: int, message: str, status: int, started: float, **kwargs: Any) -> None:
        duration_ms = (time.perf_counter() - started) * 1000
        self.logger.log(
            level, message, extra={"status": status, "duration": f"{duration_ms:.0f}ms"}, **kwargs
        )
