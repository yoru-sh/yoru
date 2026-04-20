"""Public re-export of the request-id contextvar and middleware.

The underlying ContextVar + Starlette BaseHTTPMiddleware live in
`core.logging` and `core.request_logging` (shipped wave-7). This module is
the stable public surface for consumers — observability wave-13 C2 (metrics)
and C3 (error handlers) import from here so the live code path stays
consistent with `vault/OBSERVABILITY-V0.md` without forking a second
contextvar.

Callers treat `request_id_ctx.get()` as `str | None` — outside a request it
returns None; inside a request the middleware has set the current id.
"""
from __future__ import annotations

from apps.api.core.logging import _request_id_ctx as request_id_ctx
from apps.api.core.request_logging import (
    RequestLoggingMiddleware as RequestIdMiddleware,
)


def get_request_id() -> str:
    """Current request id, or `"-"` when no request is active.

    Use this when formatting log lines / envelopes that require a non-null
    placeholder. Raw `request_id_ctx.get()` is fine when callers want to
    distinguish "no request" from a real id.
    """
    return request_id_ctx.get() or "-"


__all__ = ["request_id_ctx", "RequestIdMiddleware", "get_request_id"]
