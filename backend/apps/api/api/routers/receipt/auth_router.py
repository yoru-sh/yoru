"""Receipt v0 — hook-token auth router.

Endpoints:
  - POST   /auth/hook-token              mint a new rcpt_* token (unauth in v0)
  - GET    /auth/hook-tokens             list caller's tokens (bearer required)
  - DELETE /auth/hook-token/{id}         soft-revoke caller's token
  - POST   /auth/logout                  revoke bearer (wave-14 C3)
  - POST   /auth/refresh                 rotate refresh token (wave-48 C1)
  - POST   /auth/password-reset-request  issue a reset token (wave-14 C4, flag-gated)
  - POST   /auth/password-reset-confirm  consume a reset token (wave-14 C4, flag-gated)

Contract: vault/BACKEND-API-V0.md §4.6–§4.8, vault/AUTH-V0.md §1(a),
vault/AUTH-HARDENING-V1.md §1/§3/§4/§6.
Token storage: raw token returned once on mint, sha256 hash persisted.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid
from datetime import UTC, timedelta

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import update as sa_update
from sqlmodel import Session as DBSession
from sqlmodel import select

from .auth_sessions_model import AuthSession
from .db import get_session
from .deps import _naive_utc_now, require_current_user
from .email.welcome import send_welcome_email
from .models import (
    HookToken,
    HookTokenListItem,
    HookTokenMintIn,
    HookTokenMintOut,
    PasswordResetConfirmIn,
    PasswordResetConfirmOut,
    PasswordResetRequestIn,
    PasswordResetRequestOut,
    PasswordResetToken,
    User,
    WelcomeEmailOut,
)

# Idempotency window for /auth/welcome-email — second call inside this
# window after a successful send is a no-op (returns sent=False with the
# original timestamp). Matches the wave-54 task brief acceptance criteria.
_WELCOME_EMAIL_DEDUPE_WINDOW = timedelta(minutes=5)

_TOKEN_PREFIX = "rcpt_"
_BEARER_PREFIX = "Bearer "
_RESET_TOKEN_PREFIX = "rcpt_reset_"
_RESET_TOKEN_TTL = timedelta(hours=1)

# AUTH-HARDENING-V1 §2 — split access/refresh lifetimes.
_ACCESS_TTL = timedelta(minutes=15)
_REFRESH_TTL = timedelta(days=30)
_JWT_ALGO = "HS256"
_REFRESH_COOKIE = "refresh_token"
_DEV_JWT_SECRET = "dev-only-unsafe-change-me"

_logger = logging.getLogger(__name__)

# Warn once at import when the JWT secret is unset — tests and local dev fall
# back to a known-unsafe constant. Prod MUST set AUTH_JWT_SECRET.
if not os.environ.get("AUTH_JWT_SECRET"):
    _logger.warning(
        "AUTH_JWT_SECRET unset — access tokens will be signed with the "
        "dev-only fallback secret. Do NOT deploy this way."
    )


def _jwt_secret() -> str:
    return os.environ.get("AUTH_JWT_SECRET") or _DEV_JWT_SECRET


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _epoch(dt) -> int:
    """Convert a naive-UTC datetime to an integer epoch second."""
    return int(dt.replace(tzinfo=UTC).timestamp())


# Future-complete email body. Delivery is deferred (wave-14 C4 ships plumbing
# only); wiring Resend/Supabase is tracked in vault/audits/auth-password-reset-design.md.
PASSWORD_RESET_EMAIL_TEMPLATE = """\
Subject: Reset your Receipt password

Hi,

We received a request to reset the password for the Receipt account
tied to this email address. If you didn't ask for this, you can ignore
this message.

To set a new password, open this link within the next hour:

    {reset_link}

The link can be used once. After that, request a new one if you still
need to reset.

— Receipt
"""


def _password_reset_enabled() -> bool:
    """Feature flag for wave-14 C4 reset plumbing.

    Env-driven (mirrors the `RATELIMIT_ENABLED` pattern in
    `api/core/ratelimit.py`), default false. When false, both reset
    endpoints 404 so the route surface is indistinguishable from an
    unknown path (no information leak about the feature's existence).
    """
    v = os.environ.get("AUTH_PASSWORD_RESET_ENABLED", "").strip().lower()
    return v in ("1", "true", "yes", "on")


class AuthRouter:
    """Hook-token lifecycle (mint / list / revoke)."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/auth", tags=["receipt:auth"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.post(
            "/hook-token",
            response_model=HookTokenMintOut,
            status_code=status.HTTP_201_CREATED,
        )(self.mint_token)
        self.router.get(
            "/hook-tokens",
            response_model=list[HookTokenListItem],
        )(self.list_tokens)
        self.router.delete(
            "/hook-token/{token_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            response_model=None,
        )(self.revoke_token)
        self.router.post(
            "/logout",
            status_code=status.HTTP_204_NO_CONTENT,
            response_model=None,
        )(self.logout)
        self.router.post(
            "/refresh",
            response_model=None,
        )(self.refresh)
        self.router.post(
            "/password-reset-request",
            response_model=PasswordResetRequestOut,
            status_code=status.HTTP_202_ACCEPTED,
        )(self.password_reset_request)
        self.router.post(
            "/password-reset-confirm",
            response_model=PasswordResetConfirmOut,
        )(self.password_reset_confirm)
        self.router.post(
            "/welcome-email",
            response_model=WelcomeEmailOut,
        )(self.welcome_email)

    def mint_token(
        self,
        body: HookTokenMintIn,
        db: DBSession = Depends(get_session),
    ) -> HookTokenMintOut:
        """Create a new hook-token. Raw value is returned **once**; only
        the sha256 hash is persisted. v0 is unauthenticated (per CLI-V0-
        DESIGN §5.1); Supabase JWT gating is deferred to v1.
        """
        raw = _TOKEN_PREFIX + secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        row = HookToken(
            id=uuid.uuid4().hex,
            user=body.user,
            token_hash=token_hash,
            label=body.label,
            created_at=_naive_utc_now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return HookTokenMintOut(token=raw, user_id=row.id, user=row.user)

    def list_tokens(
        self,
        db: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> list[HookTokenListItem]:
        """List every hook-token (active + revoked) belonging to the caller."""
        rows = db.exec(
            select(HookToken)
            .where(HookToken.user == current_user)
            .order_by(HookToken.created_at.desc())
        ).all()
        return [HookTokenListItem.model_validate(r.model_dump()) for r in rows]

    def revoke_token(
        self,
        token_id: str,
        db: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> None:
        """Soft-revoke: set `revoked_at = now()`.

        Per AUTH-V0 §1(a): 401 when the token belongs to a different user
        (not 404 — spec is explicit), 404 when token_id is unknown,
        idempotent 204 when already revoked.
        """
        row = db.get(HookToken, token_id)
        if row is None:
            raise HTTPException(status_code=404, detail="token not found")
        if row.user != current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="token does not belong to caller",
            )
        if row.revoked_at is None:
            row.revoked_at = _naive_utc_now()
            db.add(row)
            db.commit()
        return None

    def logout(
        self,
        authorization: str | None = Header(default=None),
        db: DBSession = Depends(get_session),
    ) -> None:
        """Revoke the bearer in the Authorization header.

        Stamps `revoked_at` on the matching `hook_tokens` row. 401 when the
        header is missing, malformed, or the token is unknown / already
        revoked — matches AUTH-V0 posture and prevents replay after logout.
        """
        if authorization is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authorization required",
            )
        if not authorization.startswith(_BEARER_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid authorization scheme",
            )
        token = authorization[len(_BEARER_PREFIX):].strip()
        if not token.startswith(_TOKEN_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid token format",
            )
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = db.exec(
            select(HookToken).where(
                HookToken.token_hash == token_hash,
                HookToken.revoked_at.is_(None),  # type: ignore[union-attr]
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or revoked token",
            )
        row.revoked_at = _naive_utc_now()
        db.add(row)
        db.commit()
        return None

    async def refresh(
        self,
        request: Request,
        db: DBSession = Depends(get_session),
    ):
        """Rotate a refresh token (AUTH-HARDENING-V1 §3/§4).

        Cookie first, JSON body (`{"refresh_token": ...}`) second.
        - unknown hash             -> 401 `{"error": "auth_unknown"}`
        - expired-not-revoked      -> 401 `{"error": "auth_expired"}` (family untouched)
        - revoked (REUSE)          -> 401 `{"error": "auth_revoked"}` + revoke every
                                      live sibling in the family + WARN log
        - valid                    -> 200 with new access JWT + new refresh token,
                                      refresh cookie rotated, old row stamped
                                      `last_used_at` then `revoked_at`
        """
        raw = request.cookies.get(_REFRESH_COOKIE)
        if not raw:
            try:
                body = await request.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                val = body.get("refresh_token")
                if isinstance(val, str) and val:
                    raw = val

        if not raw:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "auth_unknown"},
            )

        presented_hash = _hash_refresh(raw)
        row = db.exec(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == presented_hash
            )
        ).first()
        if row is None:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "auth_unknown"},
            )

        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "")[:256]

        # §4 reuse detection — presented a row that was already consumed.
        if row.revoked_at is not None:
            family_id = row.family_id
            user_email = row.user_email
            now = _naive_utc_now()
            db.execute(
                sa_update(AuthSession)
                .where(AuthSession.family_id == family_id)
                .where(AuthSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            db.commit()
            _logger.warning(
                "event=refresh_family_reuse family_id=%s user_email=%s ip=%s ua=%s",
                family_id, user_email, ip, ua,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "auth_revoked"},
            )

        now = _naive_utc_now()
        if row.expires_at <= now:
            # Stale cookie — do NOT revoke the family (§4 edge case).
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "auth_expired"},
            )

        # §3 rotation-on-use: mint new token + row, stamp old row, single txn.
        new_raw = secrets.token_urlsafe(32)
        new_hash = _hash_refresh(new_raw)
        new_id = uuid.uuid4().hex
        new_row = AuthSession(
            id=new_id,
            user_email=row.user_email,
            refresh_token_hash=new_hash,
            issued_at=now,
            expires_at=now + _REFRESH_TTL,
            family_id=row.family_id,
            parent_token_hash=presented_hash,
            ip=ip,
            user_agent=ua,
        )
        row.last_used_at = now
        row.revoked_at = now
        db.add(row)
        db.add(new_row)
        db.commit()

        access_exp = now + _ACCESS_TTL
        access_token = jwt.encode(
            {
                "sub": row.user_email,
                "sid": new_id,
                "iat": _epoch(now),
                "exp": _epoch(access_exp),
            },
            _jwt_secret(),
            algorithm=_JWT_ALGO,
        )

        response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "access_token": access_token,
                "refresh_token": new_raw,
                "expires_in": int(_ACCESS_TTL.total_seconds()),
                "token_type": "bearer",
            },
        )
        response.set_cookie(
            key=_REFRESH_COOKIE,
            value=new_raw,
            max_age=int(_REFRESH_TTL.total_seconds()),
            httponly=True,
            samesite="lax",
            secure=False,  # dev — TLS termination handles secure=True in prod
        )
        return response

    def password_reset_request(
        self,
        body: PasswordResetRequestIn,
        db: DBSession = Depends(get_session),
    ) -> PasswordResetRequestOut:
        """Issue a single-use, 1-hour reset token for `body.email`.

        Flag-gated: when `AUTH_PASSWORD_RESET_ENABLED` is unset/false, 404 so
        the endpoint is indistinguishable from an unknown path. When on, the
        raw token is logged to stderr with a `[DEV-ONLY …]` prefix (email
        delivery is out of scope for wave-14 — see the design note at
        vault/audits/auth-password-reset-design.md). Only the sha256 hash of
        the token is persisted.
        """
        if not _password_reset_enabled():
            raise HTTPException(status_code=404, detail="Not Found")

        raw = _RESET_TOKEN_PREFIX + secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        now = _naive_utc_now()
        row = PasswordResetToken(
            id=uuid.uuid4().hex,
            user_email=body.email,
            token_hash=token_hash,
            issued_at=now,
            expires_at=now + _RESET_TOKEN_TTL,
        )
        db.add(row)
        db.commit()

        # Dev-only surface so local testing works without an SMTP pipeline.
        # Replace with real delivery once the follow-up ticket lands (see
        # vault/audits/auth-password-reset-design.md §Follow-up).
        print(
            f"[DEV-ONLY password-reset link] email={body.email} token={raw}",
            flush=True,
        )
        return PasswordResetRequestOut(sent=True)

    def welcome_email(
        self,
        db: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> WelcomeEmailOut:
        """Fire the welcome / install-snippet email for the caller.

        Idempotent: the second call within `_WELCOME_EMAIL_DEDUPE_WINDOW`
        returns `sent=False` with the original `welcome_email_sent_at` and
        does NOT re-send. Lazily upserts the `users` row keyed by email.

        The frontend calls this once after first sign-in (Supabase magic-link
        provides email → bearer; bearer scopes the call to the caller, so no
        cross-user concern). Stub vs SMTP delivery is decided inside
        `send_welcome_email` based on `SMTP_HOST` env.
        """
        now = _naive_utc_now()
        row = db.get(User, current_user)
        if (
            row is not None
            and row.welcome_email_sent_at is not None
            and (now - row.welcome_email_sent_at) < _WELCOME_EMAIL_DEDUPE_WINDOW
        ):
            return WelcomeEmailOut(
                sent=False,
                user_email=current_user,
                welcome_email_sent_at=row.welcome_email_sent_at,
            )

        send_welcome_email(current_user)

        if row is None:
            row = User(email=current_user, welcome_email_sent_at=now)
        else:
            row.welcome_email_sent_at = now
        db.add(row)
        db.commit()
        return WelcomeEmailOut(
            sent=True,
            user_email=current_user,
            welcome_email_sent_at=now,
        )

    def password_reset_confirm(
        self,
        body: PasswordResetConfirmIn,
        db: DBSession = Depends(get_session),
    ) -> PasswordResetConfirmOut:
        """Consume a reset token and mark it used.

        Flag-gated identically to request. 401 on expired / already-used /
        unknown-hash. On success the token is stamped `used_at = now()` and
        we return a known-string body that flags the incomplete storage path
        (Receipt has no password column on users today — follow-up ticket).
        """
        if not _password_reset_enabled():
            raise HTTPException(status_code=404, detail="Not Found")

        token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
        now = _naive_utc_now()
        row = db.exec(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
            )
        ).first()
        if row is None or row.used_at is not None or row.expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or expired reset token",
            )

        row.used_at = now
        db.add(row)
        db.commit()

        # TODO(wave-follow-up): once the user model grows a `password_hash`
        # column, hash `body.new_password` (argon2id — product-lead to confirm)
        # and persist here. Tracked in vault/audits/auth-password-reset-design.md.
        _logger.warning(
            "password-reset confirm accepted but password storage not yet "
            "implemented (user_email=%s)",
            row.user_email,
        )
        return PasswordResetConfirmOut(
            reset="accepted-but-password-storage-not-implemented",
        )
