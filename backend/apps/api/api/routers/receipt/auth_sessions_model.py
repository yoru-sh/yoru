"""Refresh-token rotation storage for Receipt auth (AUTH-HARDENING-V1 §1).

One row per refresh token ever issued. `family_id` groups tokens from the
same login chain so the §4 reuse-detection sweep can revoke the whole
family in a single UPDATE.

Raw tokens never land here — only `refresh_token_hash` (sha256 hex).
"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Index, SQLModel


class AuthSession(SQLModel, table=True):
    """Refresh-token record. One row per refresh token ever issued in a family."""
    __tablename__ = "auth_sessions"

    id: str = Field(primary_key=True)
    user_email: str = Field(index=True)
    refresh_token_hash: str = Field(index=True, unique=True)
    issued_at: datetime = Field(index=True)
    expires_at: datetime = Field(index=True)
    revoked_at: datetime | None = Field(default=None, index=True)
    last_used_at: datetime | None = Field(default=None)
    ip: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    family_id: str = Field(index=True)
    parent_token_hash: str | None = Field(default=None, index=True)

    __table_args__ = (
        Index("ix_auth_sessions_family_revoked", "family_id", "revoked_at"),
    )
