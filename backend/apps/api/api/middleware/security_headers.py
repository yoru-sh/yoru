"""Security headers middleware — wave-50 C3 restore.

Applies a fixed 6-header bundle to every HTTP response. Values are frozen
by the wave-50 C3 brief — do not tune without a new wave.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_HEADERS: tuple[tuple[str, str], ...] = (
    ("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload"),
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
    (
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'",
    ),
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in _HEADERS:
            response.headers[name] = value
        return response


__all__ = ["SecurityHeadersMiddleware"]
