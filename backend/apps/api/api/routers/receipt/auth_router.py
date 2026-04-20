"""Receipt v0 — hook-token auth router.

Endpoints:
  - POST   /auth/hook-token          mint a new rcpt_* token (unauth in v0)
  - GET    /auth/hook-tokens         list caller's tokens (bearer required)
  - DELETE /auth/hook-token/{id}     soft-revoke caller's token

Contract: vault/BACKEND-API-V0.md §4.6–§4.8, vault/AUTH-V0.md §1(a).
Token storage: raw token returned once on mint, sha256 hash persisted.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session as DBSession, select

from .db import get_session
from .deps import _naive_utc_now, require_current_user
from .models import (
    HookToken,
    HookTokenListItem,
    HookTokenMintIn,
    HookTokenMintOut,
)

_TOKEN_PREFIX = "rcpt_"


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
