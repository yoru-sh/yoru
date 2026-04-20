"""Request-ID propagation + per-request JSON log line.

Inbound `X-Request-ID` is preserved (we don't collide with upstream tracing);
otherwise a uuid4 is minted. The id is stored on `request.state.request_id`,
pushed into the logging ContextVar for the duration of the request, echoed
back as an `X-Request-ID` response header, and emitted as a single structured
log line at request completion with timing + status.
"""
from __future__ import annotations

import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from apps.api.core.logging import get_logger, reset_request_id, set_request_id

_logger = get_logger("apps.api.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        token = set_request_id(request_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            _logger.info(
                "http_request",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
            reset_request_id(token)
