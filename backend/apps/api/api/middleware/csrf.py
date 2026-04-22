"""CSRF double-submit cookie protection for cookie-authenticated requests.

Pattern (OWASP-compliant):
- On signin/refresh, we set two cookies:
    * `rcpt_session` (HttpOnly — not readable from JS)
    * `rcpt_csrf`    (NOT HttpOnly — readable from JS)
- On state-changing requests (POST/PUT/PATCH/DELETE), the browser sends both
  cookies automatically. The frontend reads `rcpt_csrf` from document.cookie
  and echoes it back in the `X-CSRF-Token` header.
- This middleware rejects the request if the header and cookie don't match.
- An attacker on another origin cannot read the CSRF cookie (same-origin policy),
  so they cannot craft a request that satisfies the double-submit check, even
  when they can force a browser to send the session cookie.

Exemption rules (do NOT require CSRF):
- Safe methods (GET/HEAD/OPTIONS) — immutable per HTTP spec
- Requests WITHOUT `rcpt_session` cookie — either unauthenticated (signin,
  health) or CLI bearer auth (immune to CSRF since attacker can't make the
  browser attach an `Authorization` header)
- Auth entry-point routes (`/api/v1/auth/signin`, `/signup`, `/refresh`) —
  these SET the cookies, can't require them first
"""
from __future__ import annotations

import hmac
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

SESSION_COOKIE = "rcpt_session"
CSRF_COOKIE = "rcpt_csrf"
CSRF_HEADER = "x-csrf-token"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Routes that bypass CSRF because they set the cookies in the first place.
# Everything else under /api/v1 that mutates state is protected.
AUTH_ENTRY_POINTS = (
    "/api/v1/auth/signin",
    "/api/v1/auth/signup",
    "/api/v1/auth/refresh",
)


class CsrfMiddleware(BaseHTTPMiddleware):
    """Enforce double-submit cookie CSRF on cookie-authenticated requests."""

    def __init__(self, app: ASGIApp, exempt_prefixes: Iterable[str] = ()) -> None:
        super().__init__(app)
        self._extra_exempt = tuple(exempt_prefixes)

    async def dispatch(self, request: Request, call_next):
        if request.method in SAFE_METHODS:
            return await call_next(request)

        path = request.url.path

        if any(path.startswith(p) for p in AUTH_ENTRY_POINTS):
            return await call_next(request)
        if any(path.startswith(p) for p in self._extra_exempt):
            return await call_next(request)

        # CLI hook-token flow has no session cookie — let the bearer path handle auth.
        if SESSION_COOKIE not in request.cookies:
            return await call_next(request)

        cookie_token = request.cookies.get(CSRF_COOKIE, "")
        header_token = request.headers.get(CSRF_HEADER, "")

        if not cookie_token or not header_token:
            return JSONResponse(
                {"detail": "CSRF token missing"},
                status_code=403,
            )

        if not hmac.compare_digest(cookie_token, header_token):
            return JSONResponse(
                {"detail": "CSRF token mismatch"},
                status_code=403,
            )

        return await call_next(request)
