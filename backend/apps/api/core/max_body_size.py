"""Max-body-size ASGI middleware — wave-13 B4.

Rejects oversized POST bodies on the Receipt ingest paths BEFORE FastAPI
parses the JSON. `EventsBatchIn.events: list[EventIn] = Field(max_length=1000)`
only bounds array length AFTER parse — a multi-megabyte single-event body
still pins the process during JSON load. This middleware fails fast on
`Content-Length` (and, as a fallback, on streamed byte count) so the worker
never touches attacker-controlled payloads.

Scoped narrowly:
    POST /api/v1/events
    POST /api/v1/ingest
    POST /api/v1/sessions/events

Every other method / path passes through untouched. The configurable cap
reads `MAX_BODY_SIZE_BYTES` from the environment (default 262144 / 256 KiB —
~10x the size of a realistic Claude Code hook batch).

The 413 response uses the canonical error envelope from
`apps/api/api/core/errors.py` (wave-13 C3 shape). `request_id` is populated
from `request.state.request_id` (set upstream by `RequestLoggingMiddleware`)
with the logging ContextVar as a defensive fallback.

Wire in `main.py` AFTER `CORSMiddleware` so the 413 reject runs OUTSIDE
(before) CORS in the request flow, and INSIDE `RequestLoggingMiddleware` so
the id is already minted.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apps.api.api.core.errors import envelope

_DEFAULT_GUARDED_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/events",
        "/api/v1/ingest",
        "/api/v1/sessions/events",
    }
)


class MaxBodySizeMiddleware:
    """Reject POST bodies that exceed `max_bytes` on the ingest paths."""

    def __init__(
        self,
        app: ASGIApp,
        max_bytes: Optional[int] = None,
        guarded_paths: Optional[Iterable[str]] = None,
    ) -> None:
        self.app = app
        self.max_bytes = (
            max_bytes
            if max_bytes is not None
            else int(os.environ.get("MAX_BODY_SIZE_BYTES", "262144"))
        )
        self.guarded_paths = (
            frozenset(guarded_paths)
            if guarded_paths is not None
            else _DEFAULT_GUARDED_PATHS
        )

    def _applies(self, scope: Scope) -> bool:
        if scope.get("type") != "http":
            return False
        if scope.get("method") != "POST":
            return False
        return scope.get("path", "") in self.guarded_paths

    def _reason(self, path: str) -> str:
        return f"body exceeds {self.max_bytes} bytes on {path}"

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, path: str
    ) -> None:
        request = Request(scope, receive)
        resp = envelope(
            code="PAYLOAD_TOO_LARGE",
            message=self._reason(path),
            status=413,
            request=request,
        )
        await resp(scope, receive, send)

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if not self._applies(scope):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Fast path: declared Content-Length — one comparison, zero body reads.
        declared: Optional[int] = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break

        if declared is not None:
            if declared > self.max_bytes:
                await self._reject(scope, receive, send, path)
                return
            # Declared AND within cap — pass through without draining.
            await self.app(scope, receive, send)
            return

        # Slow path: chunked / missing Content-Length — count as we stream.
        buffered: list[Message] = []
        received = 0
        more_body = True
        while more_body:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":
                more_body = False
                continue
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                await self._reject(scope, receive, send, path)
                return
            more_body = message.get("more_body", False)

        iterator = iter(buffered)

        async def replay() -> Message:
            try:
                return next(iterator)
            except StopIteration:
                return await receive()

        await self.app(scope, replay, send)


__all__ = ["MaxBodySizeMiddleware"]
