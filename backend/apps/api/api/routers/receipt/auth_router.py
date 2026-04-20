"""Receipt v0 — hook-token auth router.

Endpoints:
  - POST   /auth/hook-token              mint a new rcpt_* token (unauth in v0)
  - GET    /auth/hook-tokens             list caller's tokens (bearer required)
  - DELETE /auth/hook-token/{id}         soft-revoke caller's token
  - POST   /auth/logout                  revoke bearer (wave-14 C3)
  - POST   /auth/password-reset-request  issue a reset token (wave-14 C4, flag-gated)
  - POST   /auth/password-reset-confirm  consume a reset token (wave-14 C4, flag-gated)

Contract: vault/BACKEND-API-V0.md §4.6–§4.8, vault/AUTH-V0.md §1(a).
Token storage: raw token returned once on mint, sha256 hash persisted.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlmodel import Session as DBSession, select

from .db import get_session
from .deps import _naive_utc_now, require_current_user
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
)

_TOKEN_PREFIX = "rcpt_"
_BEARER_PREFIX = "Bearer "
_RESET_TOKEN_PREFIX = "rcpt_reset_"
_RESET_TOKEN_TTL = timedelta(hours=1)

_logger = logging.getLogger(__name__)


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
            "/password-reset-request",
            response_model=PasswordResetRequestOut,
            status_code=status.HTTP_202_ACCEPTED,
        )(self.password_reset_request)
        self.router.post(
            "/password-reset-confirm",
            response_model=PasswordResetConfirmOut,
        )(self.password_reset_confirm)

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
