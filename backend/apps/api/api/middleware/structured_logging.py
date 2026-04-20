"""Structured JSON access log — wave-40 C1.

Emits one JSON line per HTTP request to stdout. Schema frozen by
wave-40 C1 brief: ``timestamp``, ``level``, ``request_id``, ``method``,
``path``, ``status``, ``latency_ms``, ``user_id``.

The middleware picks up ``request.state.request_id`` when upstream
(wave-40 C2) has already minted one, and otherwise generates a
``uuid4().hex`` fallback so this middleware is useful standalone. C2
takes over the generation step once it lands; this file does not need
to change.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_LOGGER_NAME = "receipt.http"
_LOG_RECORD_EXTRA_KEY = "_receipt_http"
_STRUCTURED_HANDLER_MARK = "_receipt_structured_http"

# Map stdlib level numbers to the lowercase set required by the brief.
_LEVEL_MAP = {
    logging.DEBUG: "info",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


class StructuredAccessLogFormatter(logging.Formatter):
    """Serialize a request record to the 7-field JSON envelope."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict[str, Any] = getattr(record, _LOG_RECORD_EXTRA_KEY, None) or {}
        envelope = {
            "timestamp": payload.get(
                "timestamp",
                datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            ),
            "level": _LEVEL_MAP.get(record.levelno, "info"),
            "request_id": payload.get("request_id", ""),
            "method": payload.get("method", ""),
            "path": payload.get("path", ""),
            "status": payload.get("status", 0),
            "latency_ms": payload.get("latency_ms", 0),
            "user_id": payload.get("user_id", None),
        }
        return json.dumps(envelope, separators=(",", ":"), default=str)


def configure_structured_logger(level: int = logging.INFO) -> logging.Logger:
    """Install the JSON stdout handler on the access logger. Idempotent.

    Called from ``apps/api/main.py`` lifespan startup. Re-calls replace the
    existing handler so hot-reload cycles do not duplicate log lines.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, _STRUCTURED_HANDLER_MARK, False):
            logger.handlers.clear()
            break
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredAccessLogFormatter())
    setattr(handler, _STRUCTURED_HANDLER_MARK, True)
    logger.handlers.append(handler)
    return logger


def _level_for_status(status: int) -> int:
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.INFO


def _resolve_user_id(request: Request) -> str | None:
    user = getattr(request.state, "user", None)
    if user is None:
        return None
    if isinstance(user, str):
        return user
    for attr in ("id", "user_id", "email"):
        value = getattr(user, attr, None)
        if value:
            return str(value)
    if isinstance(user, dict):
        for key in ("id", "user_id", "email"):
            value = user.get(key)
            if value:
                return str(value)
    return None


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Emit one structured JSON log line per request after the response.

    Reads ``request.state.request_id`` when upstream has set one; otherwise
    mints a fresh ``uuid4().hex`` and stores it on the state so downstream
    handlers and the ``X-Request-ID`` response header agree.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = getattr(request.state, "request_id", None) or uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        status = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers.setdefault("X-Request-ID", request_id)
            return response
        finally:
            latency_ms = int(round((time.perf_counter() - start) * 1000))
            payload = {
                "timestamp": datetime.now(UTC).isoformat(),
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "latency_ms": latency_ms,
                "user_id": _resolve_user_id(request),
            }
            logging.getLogger(_LOGGER_NAME).log(
                _level_for_status(status),
                "http_request",
                extra={_LOG_RECORD_EXTRA_KEY: payload},
            )


__all__ = [
    "StructuredAccessLogFormatter",
    "StructuredLoggingMiddleware",
    "configure_structured_logger",
]
