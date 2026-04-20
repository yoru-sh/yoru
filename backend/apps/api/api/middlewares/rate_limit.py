"""Token-bucket rate-limit middleware for the ingest endpoint.

Pure-stdlib (no Redis). Single-process v0 — bucket lives in-memory keyed by
client host. Defaults: 60 req/min, burst 30. Override via env
`RATE_LIMIT_INGEST_PER_MIN` and `RATE_LIMIT_INGEST_BURST`. Scoped to a single
path prefix at wire-time so the SPA isn't penalized by ingest spikes.
"""
from __future__ import annotations

import math
import os
import time
from typing import Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        path_prefix: str = "/api/v1/sessions/events",
        per_min: Optional[int] = None,
        burst: Optional[int] = None,
    ) -> None:
        self.app = app
        self.path_prefix = path_prefix
        self.per_min = (
            per_min
            if per_min is not None
            else int(os.environ.get("RATE_LIMIT_INGEST_PER_MIN", "60"))
        )
        self.burst = (
            burst
            if burst is not None
            else int(os.environ.get("RATE_LIMIT_INGEST_BURST", "30"))
        )
        self.rate_per_sec = self.per_min / 60.0 if self.per_min > 0 else 0.0
        self._buckets: dict[str, tuple[float, float]] = {}

    def _matches(self, path: str) -> bool:
        return path == self.path_prefix or path.startswith(self.path_prefix + "/")

    def _consume(self, key: str, now: float) -> Optional[int]:
        """Try to take 1 token. Return None if allowed, else Retry-After seconds."""
        tokens, last = self._buckets.get(key, (float(self.burst), now))
        if self.rate_per_sec > 0:
            tokens = min(float(self.burst), tokens + (now - last) * self.rate_per_sec)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            return None
        self._buckets[key] = (tokens, now)
        if self.rate_per_sec <= 0:
            return 60
        seconds_needed = (1.0 - tokens) / self.rate_per_sec
        return max(1, math.ceil(seconds_needed))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._matches(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        client = scope.get("client") or ("unknown", 0)
        retry_after = self._consume(client[0], time.monotonic())
        if retry_after is None:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            status_code=429,
            content={"detail": "rate limit exceeded"},
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)
