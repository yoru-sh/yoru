"""SQLModel tables + request/response schemas for Receipt v0.

Single source of truth for all Receipt shapes. Routers import from here.
Contract frozen in vault/BACKEND-API-V0.md §2–§3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import model_validator
from sqlmodel import JSON, Column, Field, SQLModel

EventKind = Literal["tool_use", "file_change", "token", "error", "session_start", "session_end"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- Tables ----------

class Session(SQLModel, table=True):
    """Denormalized per-agent-session row."""
    __tablename__ = "sessions"

    id: str = Field(primary_key=True)
    user: str = Field(index=True)
    agent: str = Field(default="claude-code")
    started_at: datetime = Field(default_factory=_utcnow, index=True)
    ended_at: Optional[datetime] = Field(default=None)
    tools_count: int = 0
    files_count: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = Field(default=0.0, index=True)
    flagged: bool = Field(default=False, index=True)
    flags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    files_changed: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    tools_called: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    summary: Optional[str] = Field(default=None)


class Event(SQLModel, table=True):
    """Append-only event stream keyed by session."""
    __tablename__ = "events"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True, foreign_key="sessions.id")
    ts: datetime = Field(default_factory=_utcnow, index=True)
    kind: str = Field(index=True)
    tool: Optional[str] = None
    path: Optional[str] = None
    content: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    flags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    raw: Optional[dict] = Field(default=None, sa_column=Column(JSON))


class HookToken(SQLModel, table=True):
    """Opaque hook-token minted for the Claude Code hook (CLI-V0-DESIGN §5.1)."""
    __tablename__ = "hook_tokens"

    id: str = Field(primary_key=True)
    user: str = Field(index=True)
    token_hash: str = Field(index=True, unique=True)
    label: Optional[str] = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=_utcnow)
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class PasswordResetToken(SQLModel, table=True):
    """Single-use password-reset token (wave-14 C4; feature-flagged off by default).

    sha256 of the opaque raw token is what's persisted — same discipline as
    `HookToken.token_hash`. Rows are kept (not deleted on use) so replay
    attempts land on a used-at branch and 401 instead of 404.
    """
    __tablename__ = "password_reset_tokens"

    id: str = Field(primary_key=True)
    user_email: str = Field(index=True, max_length=320)
    token_hash: str = Field(index=True, unique=True)
    issued_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime
    used_at: Optional[datetime] = None


# ---------- Ingestion ----------

class EventIn(SQLModel):
    """Incoming event from a Claude Code hook.

    `user` is optional: when absent, the events router derives it from the
    bearer token (see events_router + deps.get_current_user). Rejected with
    422 when neither is present. Bodies that carry `user` keep the v0
    'user field is trusted' contract for backward compatibility with
    scripts/smoke-us14.sh and any ingestor that doesn't authenticate.

    `kind` is optional: when absent, the events router classifies it from
    `tool`/`tool_name` (Write|Edit|MultiEdit → file_change, else tool_use).
    Closes gap #3 for the real Claude Code hook stdin shape, which carries
    `tool_name` and no `kind`.

    `tool_name` is accepted as a JSON alias for `tool` to match the Claude
    Code hook stdin key verbatim without breaking v0 callers that send `tool`.
    """
    session_id: str
    user: Optional[str] = None
    kind: Optional[EventKind] = None
    ts: Optional[datetime] = None
    tool: Optional[str] = None
    path: Optional[str] = None
    content: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    raw: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _accept_tool_name_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tool_name" in data and "tool" not in data:
            data = {**data, "tool": data["tool_name"]}
            data.pop("tool_name", None)
        return data


class EventsBatchIn(SQLModel):
    events: list[EventIn] = Field(min_length=1, max_length=1000)


class IngestAck(SQLModel):
    accepted: int
    session_ids: list[str]
    flagged_sessions: list[str]


# ---------- Listing ----------

class SessionListItem(SQLModel):
    id: str
    user: str
    agent: str
    started_at: datetime
    ended_at: Optional[datetime]
    tools_count: int
    files_count: int
    tokens_input: int
    tokens_output: int
    cost_usd: float
    flagged: bool
    flags: list[str]


class SessionListResponse(SQLModel):
    items: list[SessionListItem]
    total: int
    limit: int
    offset: int


# ---------- Detail ----------

class EventOut(SQLModel):
    id: int
    ts: datetime
    kind: str
    tool: Optional[str]
    path: Optional[str]
    content: Optional[str]
    tokens_input: int
    tokens_output: int
    cost_usd: float
    flags: list[str]
    # v1 enrichment — computed at serialization time (sessions_router), not persisted.
    duration_ms: Optional[int] = None
    group_key: Optional[str] = None
    # Truncated tool_response preview for the timeline (stdout + stderr + error).
    output: Optional[str] = None


class SessionDetail(SessionListItem):
    files_changed: list[str]
    tools_called: list[str]
    summary: Optional[str]
    events: list[EventOut]


# ---------- Trail export (§4.6) ----------

class TrailSession(SessionListItem):
    """Session envelope for `/sessions/{id}/trail` — SessionDetail minus events."""
    files_changed: list[str]
    tools_called: list[str]
    summary: Optional[str]


class TrailOut(SQLModel):
    session: TrailSession
    events: list[EventOut]
    exported_at: datetime
    schema_version: str = "v0"


# ---------- Summary ----------

class SummaryOut(SQLModel):
    session_id: str
    summary: str
    generated_at: datetime


# ---------- Auth (hook-token mint/list/revoke) ----------

class HookTokenMintIn(SQLModel):
    user: str = Field(min_length=1, max_length=128)
    label: Optional[str] = Field(default=None, max_length=128)


class HookTokenMintOut(SQLModel):
    token: str
    user_id: str
    user: str


class HookTokenListItem(SQLModel):
    id: str
    label: Optional[str]
    created_at: datetime
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]


# ---------- Password reset (wave-14 C4) ----------

class PasswordResetRequestIn(SQLModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetRequestOut(SQLModel):
    sent: bool


class PasswordResetConfirmIn(SQLModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class PasswordResetConfirmOut(SQLModel):
    reset: str


# ---------- Team dashboard ----------

class TeamDashboardUser(SQLModel):
    email: str
    sessions: int
    flagged: int
    total_cost_usd: float


class TeamDashboardTotals(SQLModel):
    sessions: int
    flagged: int
    flagged_pct: float


class TeamDashboardOut(SQLModel):
    users: list[TeamDashboardUser]
    totals: TeamDashboardTotals
