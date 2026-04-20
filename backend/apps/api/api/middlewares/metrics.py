"""STUB — in-memory only, process-local, lost on restart. Replace with prometheus-client in v1.

In-process request counter middleware. Wraps ASGI `send` to capture the response
status, reads the matched route's templated path from `scope["route"].path` so
URLs like `/api/v1/sessions/abc123` collapse to `/api/v1/sessions/{session_id}`
and don't blow up cardinality. Exposes a Prometheus-text snapshot via the
`render_prometheus()` helper consumed by the `/metrics` route in main.py.

Skipped on purpose:
- Unmatched paths (no `scope["route"]`): we don't record them, so 404 scanners
  can't inflate the counter map.
- The `/metrics` endpoint itself: avoids self-counting noise.
"""
from __future__ import annotations

import threading
from typing import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# (method, path_template, status) -> count
_counter: dict[tuple[str, str, int], int] = {}
_lock = threading.Lock()

# Paths we never want to record. /metrics so it doesn't self-count.
_EXCLUDE_PATHS: frozenset[str] = frozenset({"/metrics"})

_METRIC_NAME = "receipt_http_requests_total"


def increment(method: str, path_template: str, status: int) -> None:
    key = (method, path_template, status)
    with _lock:
        _counter[key] = _counter.get(key, 0) + 1


def snapshot() -> dict[tuple[str, str, int], int]:
    with _lock:
        return dict(_counter)


def reset() -> None:
    with _lock:
        _counter.clear()


def _escape_label_value(v: str) -> str:
    # Prometheus text format: backslash, double-quote, newline must be escaped.
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_prometheus() -> str:
    lines: list[str] = [
        f"# HELP {_METRIC_NAME} Total HTTP requests by method, path template, status.",
        f"# TYPE {_METRIC_NAME} counter",
    ]
    for (method, path, status), count in sorted(snapshot().items()):
        m = _escape_label_value(method)
        p = _escape_label_value(path)
        lines.append(
            f'{_METRIC_NAME}{{method="{m}",path="{p}",status="{status}"}} {count}'
        )
    return "\n".join(lines) + "\n"


class RequestMetricsMiddleware:
    def __init__(self, app: ASGIApp, exclude_paths: Iterable[str] | None = None) -> None:
        self.app = app
        self.exclude_paths = (
            frozenset(exclude_paths) if exclude_paths is not None else _EXCLUDE_PATHS
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_box: dict[str, int] = {}

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_box["status"] = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            raw_path = scope.get("path", "") or ""
            if raw_path in self.exclude_paths:
                return
            route = scope.get("route")
            template = getattr(route, "path", None)
            if not template:
                # Unmatched route — skip to avoid cardinality explosion from scanners.
                return
            status = status_box.get("status")
            if status is None:
                return
            method = scope.get("method", "") or ""
            increment(method, template, status)
