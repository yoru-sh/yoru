"""Cookie-based dashboard auth — token never reaches JavaScript.

Separate from the CLI hook-token router (`routers/receipt/auth_router.py`),
which continues to serve `Authorization: Bearer rcpt_*` for CLI tools that
can't speak cookies.

Endpoints (mounted at `/api/v1/auth`):

    POST /signup           → creates user, sets cookies, returns {user}
    POST /signin           → validates password, sets cookies, returns {user}
    POST /session/refresh  → rotates cookies using refresh-token cookie
    POST /session/signout  → clears cookies
    GET  /session/me       → returns current user (cookie-protected)

Cookies:
    rcpt_session   — Supabase access-token JWT (HttpOnly, short TTL)
    rcpt_refresh   — Supabase refresh token (HttpOnly, long TTL, scoped path)
    rcpt_csrf      — CSRF double-submit token (NOT HttpOnly; JS reads and
                     echoes back as `X-CSRF-Token` on mutating requests)

CSRF protection for state-changing requests lives in `middleware/csrf.py`.
The three entry-point routes (signup/signin/refresh) are exempt because they
SET the cookies — requiring the cookie to first exist would be a chicken/egg.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr

from apps.api.api.dependencies.auth import (
    SESSION_COOKIE_NAME,
    get_correlation_id,
    get_current_user_id_from_cookie,
)
from apps.api.api.exceptions.domain_exceptions import (
    AuthenticationError,
    ValidationError,
)
from apps.api.api.models.auth.auth_models import SignInRequest, SignUpRequest
from apps.api.api.models.user.user_models import UserResponse
from apps.api.api.services.auth.auth_service import AuthService
from libs.log_manager.controller import LoggingController
from libs.supabase.supabase import SupabaseManager

REFRESH_COOKIE_NAME = "rcpt_refresh"
CSRF_COOKIE_NAME = "rcpt_csrf"

# Cookie lifetimes — match Supabase defaults, rotatable via env.
_ACCESS_TTL = int(os.getenv("AUTH_ACCESS_TTL_SECONDS", "3600"))        # 1 h
_REFRESH_TTL = int(os.getenv("AUTH_REFRESH_TTL_SECONDS", "604800"))    # 7 d
_CSRF_TTL = _REFRESH_TTL

# Path scoping — all three cookies at `/` to avoid Chrome's "set-cookie with
# non-prefix Path gets silently dropped on send" behavior. Signin runs at
# /api/v1/auth/signin; narrower paths like /api/v1/auth/session were stored
# but never re-sent by the browser. HttpOnly + SameSite=Lax on session and
# refresh is what actually guards them; narrow-pathing was marginal privacy
# that we can re-introduce once cookies provably travel.
_ACCESS_PATH = "/"
_REFRESH_PATH = "/"
_CSRF_PATH = "/"


def _cookie_secure() -> bool:
    """True in production (HTTPS), false for local dev (http://localhost)."""
    return os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def _cookie_samesite() -> str:
    return os.getenv("COOKIE_SAMESITE", "lax")


class RefreshCookiePayload(BaseModel):
    """Only used by the service shim — the refresh router reads the cookie."""
    refresh_token: str


class SignupForm(BaseModel):
    email: EmailStr
    password: str
    first_name: str | None = None
    last_name: str | None = None
    invitation_token: str | None = None


class SessionUserResponse(BaseModel):
    user: UserResponse


def _set_session_cookies(response: Response, access: str, refresh: str) -> str:
    """Write the three auth cookies, return the CSRF token for logging."""
    csrf = secrets.token_urlsafe(32)
    secure = _cookie_secure()
    samesite = _cookie_samesite()

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=access,
        max_age=_ACCESS_TTL,
        path=_ACCESS_PATH,
        httponly=True,
        secure=secure,
        samesite=samesite,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh,
        max_age=_REFRESH_TTL,
        path=_REFRESH_PATH,
        httponly=True,
        secure=secure,
        samesite=samesite,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf,
        max_age=_CSRF_TTL,
        path=_CSRF_PATH,
        httponly=False,  # readable from JS, that's the double-submit pattern
        secure=secure,
        samesite=samesite,
    )
    return csrf


def _clear_session_cookies(response: Response) -> None:
    for name, path in (
        (SESSION_COOKIE_NAME, _ACCESS_PATH),
        (REFRESH_COOKIE_NAME, _REFRESH_PATH),
        (CSRF_COOKIE_NAME, _CSRF_PATH),
    ):
        response.delete_cookie(key=name, path=path)


class CookieAuthRouter:
    """Dashboard-only cookie-based auth."""

    def __init__(self) -> None:
        self.logger = LoggingController(app_name="CookieAuthRouter")
        self.router = APIRouter(prefix="/auth", tags=["auth:cookie"])
        self._service: AuthService | None = None
        self._setup_routes()

    def initialize_services(self) -> None:
        self._service = AuthService()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.post("/signup", status_code=201, summary="Register + set session cookies")(self.signup)
        self.router.post("/signin", status_code=200, summary="Sign in + set session cookies")(self.signin)
        self.router.post("/session/signout", status_code=204, summary="Clear session cookies")(self.signout)
        self.router.post("/session/refresh", status_code=200, summary="Rotate session via refresh cookie")(self.refresh)
        self.router.get("/session/me", status_code=200, summary="Lightweight session-aliveness check (full profile CRUD lives at /me)")(self.me)

    async def signup(
        self,
        response: Response,
        data: SignupForm,
        correlation_id: str = Depends(get_correlation_id),
    ) -> SessionUserResponse:
        if self._service is None:
            self._service = AuthService()
        signup_request = SignUpRequest(
            email=data.email,
            password=data.password,
            first_name=data.first_name,
            last_name=data.last_name,
            invitation_token=data.invitation_token,
        )
        try:
            auth_response = await self._service.sign_up(signup_request, correlation_id)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except AuthenticationError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e
        _set_session_cookies(
            response,
            access=auth_response.access_token,
            refresh=auth_response.refresh_token,
        )
        return SessionUserResponse(user=auth_response.user)

    async def signin(
        self,
        response: Response,
        data: SignInRequest,
        correlation_id: str = Depends(get_correlation_id),
    ) -> SessionUserResponse:
        if self._service is None:
            self._service = AuthService()
        try:
            auth_response = await self._service.sign_in(data, correlation_id)
        except AuthenticationError as e:
            raise HTTPException(
                status_code=401, detail="Invalid email or password"
            ) from e
        _set_session_cookies(
            response,
            access=auth_response.access_token,
            refresh=auth_response.refresh_token,
        )
        return SessionUserResponse(user=auth_response.user)

    async def signout(self, request: Request, response: Response) -> Response:
        """Clear cookies unconditionally — idempotent, no 401 if already out."""
        # Best-effort server-side sign-out so Supabase drops the refresh family.
        refresh = request.cookies.get(REFRESH_COOKIE_NAME)
        access = request.cookies.get(SESSION_COOKIE_NAME)
        if refresh and access:
            try:
                supabase = SupabaseManager()
                supabase.client.auth.sign_out()
            except Exception:
                # Cookies cleared regardless — browser-side state is what matters.
                pass
        _clear_session_cookies(response)
        response.status_code = 204
        return response

    async def refresh(
        self,
        request: Request,
        response: Response,
        correlation_id: str = Depends(get_correlation_id),
    ) -> SessionUserResponse:
        if self._service is None:
            self._service = AuthService()
        refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
        if not refresh_token:
            raise HTTPException(status_code=401, detail="No refresh cookie")
        from apps.api.api.models.auth.auth_models import RefreshRequest
        try:
            auth_response = await self._service.refresh_token(
                RefreshRequest(refresh_token=refresh_token), correlation_id
            )
        except AuthenticationError as e:
            # Clear cookies so the browser doesn't retry indefinitely.
            _clear_session_cookies(response)
            raise HTTPException(status_code=401, detail="Refresh expired") from e
        _set_session_cookies(
            response,
            access=auth_response.access_token,
            refresh=auth_response.refresh_token,
        )
        return SessionUserResponse(user=auth_response.user)

    async def me(
        self,
        user_id: UUID = Depends(get_current_user_id_from_cookie),
    ) -> SessionUserResponse:
        """Return minimal user info so the SPA's AuthProvider can init state.

        This endpoint is intentionally lightweight — it only proves the cookie
        is valid and returns the profile row. For full CRUD (PATCH, subscription,
        grants, groups, group features), the SPA calls the SaaSForge `/me`
        surface mounted separately.
        """
        supabase = SupabaseManager()
        profile: dict | None = None
        try:
            profile = supabase.get_record("profiles", str(user_id), correlation_id="")
        except Exception:
            profile = None
        p = profile or {}
        return SessionUserResponse(
            user=UserResponse(
                id=user_id,
                email=p.get("email", ""),
                first_name=p.get("first_name"),
                last_name=p.get("last_name"),
                avatar_url=p.get("avatar_url"),
                locale=p.get("locale", "en"),
                timezone=p.get("timezone", "UTC"),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
