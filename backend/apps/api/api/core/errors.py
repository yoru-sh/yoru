"""Structured JSON error envelope — wave-13 C3.

Canonical shape on every error response:

    {"error": {"code": str, "message": str, "request_id": str,
                "hint": str | null}}

Plus `X-Request-ID` header echoing the same id. `code` is machine-readable
(mapping-table fallback, or explicit via `AppError`); `message` is
human-readable; `hint` is optional guidance (e.g. first pydantic error
summary). Shape supersedes the wave-7 flat envelope documented in
ERROR-HANDLING-V0.md.

Register via `install_error_handlers(app)` once in main.py (after
middleware, before routers). Only three handlers are needed: one for
RequestValidationError (422), one for HTTPException (explicit
`AppError.code` when present, else mapping-table fallback), one for
unhandled Exception (500, traceback logged server-side).
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from apps.api.core.logging import current_request_id, get_logger

_logger = get_logger("apps.api.errors")


_STATUS_TO_CODE: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "AUTH_FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
    500: "INTERNAL",
    503: "SERVICE_UNAVAILABLE",
}


def _code_for_status(status: int) -> str:
    return _STATUS_TO_CODE.get(status, f"HTTP_{status}")


class AppError(HTTPException):
    """HTTPException carrying a machine-readable `code` and optional `hint`.

    Usage: `raise AppError(status_code=401, detail="invalid token",
    code="AUTH_INVALID_TOKEN", hint="tokens start with rcpt_")`. The
    envelope reads `code`/`hint` directly; when raised as plain
    `HTTPException`, the mapping table fills in a generic code and no hint.
    """

    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        code: str,
        hint: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.hint = hint


def _resolve_request_id(request: Request | None) -> str:
    """Best-effort request id.

    `request.state.request_id` is set by RequestLoggingMiddleware before
    `try/finally`, so it survives even when the 500 handler runs outside
    the middleware scope (ServerErrorMiddleware is outermost and the
    middleware's `finally` resets the ContextVar before the exception
    reaches us). Falls back to the ContextVar for handlers that run
    inside the middleware, then to `"-"` as the last-resort sentinel.
    """
    if request is not None:
        rid = getattr(request.state, "request_id", None)
        if rid:
            return rid
    rid = current_request_id()
    return rid or "-"


def envelope(
    code: str,
    message: str,
    status: int,
    hint: str | None = None,
    *,
    request: Request | None = None,
) -> JSONResponse:
    """Build the canonical error JSONResponse + X-Request-ID header."""
    rid = _resolve_request_id(request)
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": rid,
            "hint": hint,
        }
    }
    resp = JSONResponse(status_code=status, content=body)
    resp.headers["X-Request-ID"] = rid
    return resp


def _validation_hint(exc: RequestValidationError) -> str | None:
    errors = exc.errors()
    if not errors:
        return None
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
    msg = str(first.get("msg", "")).strip()
    summary = f"{loc}: {msg}" if loc else msg
    return summary[:200] or None


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return envelope(
        code="VALIDATION_FAILED",
        message="request validation failed",
        status=422,
        hint=_validation_hint(exc),
        request=request,
    )


async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    if isinstance(exc, AppError):
        code = exc.code
        hint = exc.hint
    else:
        code = _code_for_status(exc.status_code)
        hint = None
    message = (
        exc.detail
        if isinstance(exc.detail, str) and exc.detail
        else code.replace("_", " ").lower()
    )
    resp = envelope(
        code=code,
        message=message,
        status=exc.status_code,
        hint=hint,
        request=request,
    )
    if exc.headers:
        for key, value in exc.headers.items():
            resp.headers[key] = value
    return resp


async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    rid = _resolve_request_id(request)
    _logger.exception(
        "unhandled_exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "request_id": rid,
        },
    )
    return envelope(
        code="INTERNAL",
        message="internal server error",
        status=500,
        request=request,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register all three handlers on the app (main.py calls this once)."""
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)


__all__ = [
    "AppError",
    "envelope",
    "generic_exception_handler",
    "http_exception_handler",
    "install_error_handlers",
    "validation_exception_handler",
]
