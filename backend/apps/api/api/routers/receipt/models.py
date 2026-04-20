"""SQLModel tables + request/response schemas for Receipt v0.

Single source of truth for all Receipt shapes. Routers import from here.
Contract frozen in vault/BACKEND-API-V0.md §2–§3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from sqlmodel import JSON, Column, Field, SQLModel

EventKind = Literal["tool_use", "file_change", "token", "error"]


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


# ---------- Ingestion ----------

class EventIn(SQLModel):
    """Incoming event from a Claude Code hook."""
    session_id: str
    user: str
    kind: EventKind
    ts: Optional[datetime] = None
    tool: Optional[str] = None
    path: Optional[str] = None
    content: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    raw: Optional[dict] = None


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
