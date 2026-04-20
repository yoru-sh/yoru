"""Shared FastAPI dependencies for Receipt v0 routers.

`get_current_user` resolves a `rcpt_<...>` bearer token to the bound user
string by looking up the sha256 hash in `hook_tokens` (revoked_at IS NULL).

Behavior:
- header absent                  -> return None (backward-compat; events
                                    router falls back to `EventIn.user`)
- header present but malformed   -> 401
- header present, token unknown
  or revoked                     -> 401
- header present, token valid    -> return the bound `user` string

`require_current_user` is the strict variant — raises 401 even when the
header is absent. Not wired in v0 but exported for future routes.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session as DBSession, select

from .db import get_session
from .models import HookToken

_BEARER_PREFIX = "Bearer "
_TOKEN_PREFIX = "rcpt_"


def _naive_utc_now() -> datetime:
    """Naive UTC — SQLite drops tzinfo so everything persisted is naive
    (self-learning: SQLite drops tzinfo gotcha)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _resolve_token(authorization: str, session: DBSession) -> str:
    """Parse 'Bearer rcpt_...' and return the bound user or raise 401.

    Side-effect: updates `last_used_at` (naive UTC) on the matched row so
    `GET /auth/hook-tokens` can show a freshness indicator.
    """
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
    row = session.exec(
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
    row.last_used_at = _naive_utc_now()
    session.add(row)
    session.commit()
    return row.user


def get_current_user(
    authorization: str | None = Header(default=None),
    session: DBSession = Depends(get_session),
) -> str | None:
    """Optional bearer — returns None when header absent (v0 backward-compat)."""
    if authorization is None:
        return None
    return _resolve_token(authorization, session)


def require_current_user(
    authorization: str | None = Header(default=None),
    session: DBSession = Depends(get_session),
) -> str:
    """Strict bearer — 401 on missing header."""
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authorization required",
        )
    return _resolve_token(authorization, session)
