"""Receipt v0 — sessions list + detail router.

Owner: dev-B. Contract: vault/BACKEND-API-V0.md §4.2, §4.3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlmodel import Session as SQLSession, select

from .db import get_session
from .deps import require_current_user
from .models import (
    Event,
    EventOut,
    Session as SessionRow,
    SessionDetail,
    SessionListItem,
    SessionListResponse,
    TrailOut,
    TrailSession,
)

# Tool-name classes for path/content extraction (v1 timeline enrichment).
_FILE_TOOLS = frozenset({"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"})


def _enrich_events(events_asc: list[Event]) -> list[EventOut]:
    """Compute tool/path/content/duration_ms/group_key per event for the frontend
    timeline. Pure serialization-time enrichment — nothing persists to the DB."""
    out: list[EventOut] = []
    n = len(events_asc)
    for i, e in enumerate(events_asc):
        raw = e.raw if isinstance(e.raw, dict) else {}
        tool_input = raw.get("tool_input") if isinstance(raw.get("tool_input"), dict) else {}
        tool = e.tool or (raw.get("tool_name") if isinstance(raw.get("tool_name"), str) else None)
        path = e.path
        if path is None:
            if tool in _FILE_TOOLS and isinstance(tool_input.get("file_path"), str):
                path = tool_input["file_path"]
            elif tool == "Bash" and isinstance(tool_input.get("command"), str):
                path = tool_input["command"][:80]
            elif tool == "Grep" and isinstance(tool_input.get("pattern"), str):
                path = tool_input["pattern"]
            elif tool == "WebSearch" and isinstance(tool_input.get("query"), str):
                path = tool_input["query"]
        content = e.content
        if content is None:
            src = None
            if tool == "Bash":
                src = tool_input.get("command")
            elif tool == "Edit":
                src = tool_input.get("old_string")
            elif tool == "Write":
                src = tool_input.get("content")
            elif tool == "Grep":
                src = tool_input.get("pattern")
            elif tool == "Read":
                src = tool_input.get("file_path")
            elif tool == "WebSearch":
                src = tool_input.get("query")
            elif tool == "WebFetch":
                src = tool_input.get("url")
            elif tool == "Task":
                src = tool_input.get("description")
            elif tool == "TodoWrite":
                todos = tool_input.get("todos")
                if isinstance(todos, list) and todos:
                    first = todos[0]
                    if isinstance(first, dict):
                        src = first.get("content") or first.get("activeForm")
            if isinstance(src, str):
                content = src[:200]
            elif content is None and isinstance(tool, str) and tool_input:
                # Generic fallback for MCP tools and anything else:
                # pick the first non-empty string value from tool_input, prefixed by its key.
                try:
                    for k, v in tool_input.items():
                        if isinstance(v, str) and v.strip():
                            content = f"{k}={v}"[:200]
                            break
                        elif isinstance(v, (int, float, bool)) and v is not None:
                            content = f"{k}={v}"[:200]
                            break
                        elif isinstance(v, (list, dict)) and v:
                            import json as _json
                            content = f"{k}={_json.dumps(v)}"[:200]
                            break
                except Exception:
                    pass
        duration_ms: Optional[int] = None
        if i < n - 1:
            duration_ms = int(round((events_asc[i + 1].ts - e.ts).total_seconds() * 1000))
        group_key = f"{tool}:{(path or content or '')[:40]}"
        # Extract tool_response preview for timeline. Shapes by tool type:
        # - Bash: dict{stdout,stderr,error}
        # - Read: dict{content}
        # - Edit/Write: dict{message|content}
        # - MCP tools (mcp__*): list[{type:"text", text:"..."}]
        # - Sometimes plain string.
        output: Optional[str] = None
        tr = raw.get("tool_response")
        if isinstance(tr, dict):
            parts = []
            if isinstance(tr.get("stdout"), str) and tr["stdout"]:
                parts.append(tr["stdout"])
            if isinstance(tr.get("stderr"), str) and tr["stderr"]:
                parts.append(tr["stderr"])
            if isinstance(tr.get("error"), str) and tr["error"]:
                parts.append(f"error: {tr['error']}")
            if isinstance(tr.get("content"), str) and tr["content"]:
                parts.append(tr["content"])
            if isinstance(tr.get("message"), str) and tr["message"]:
                parts.append(tr["message"])
            blob = "\n".join(parts).strip()
            if blob:
                output = blob[:800]
        elif isinstance(tr, list) and tr:
            # MCP shape: list of {type:"text", text:"..."} items.
            parts = []
            for item in tr:
                if isinstance(item, dict) and item.get("type") == "text":
                    t = item.get("text")
                    if isinstance(t, str):
                        parts.append(t)
                elif isinstance(item, str):
                    parts.append(item)
            blob = "\n".join(parts).strip()
            if blob:
                output = blob[:800]
        elif isinstance(tr, str) and tr.strip():
            output = tr[:800]
        out.append(EventOut.model_validate({
            **e.model_dump(),
            "tool": tool,
            "path": path,
            "content": content,
            "duration_ms": duration_ms,
            "group_key": group_key,
            "output": output,
        }))
    return out


class SessionsRouter:
    """Read endpoints for Receipt sessions (list + detail)."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/sessions", tags=["receipt:sessions"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.get("", response_model=SessionListResponse)(self.list_sessions)
        self.router.get("/{session_id}", response_model=SessionDetail)(
            self.get_session_detail
        )
        self.router.get("/{session_id}/trail", response_model=TrailOut)(
            self.get_session_trail
        )

    def list_sessions(
        self,
        from_ts: Optional[datetime] = None,
        to_ts: Optional[datetime] = None,
        flagged: Optional[bool] = None,
        min_cost: Optional[float] = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        db: SQLSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> SessionListResponse:
        filters = [SessionRow.user == current_user]
        if from_ts is not None:
            filters.append(SessionRow.started_at >= from_ts)
        if to_ts is not None:
            filters.append(SessionRow.started_at <= to_ts)
        if flagged is not None:
            filters.append(SessionRow.flagged == flagged)
        if min_cost is not None:
            filters.append(SessionRow.cost_usd >= min_cost)

        list_stmt = (
            select(SessionRow)
            .where(*filters)
            .order_by(SessionRow.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
        count_stmt = select(func.count()).select_from(SessionRow).where(*filters)

        rows = db.exec(list_stmt).all()
        total = db.exec(count_stmt).one()

        items = [SessionListItem.model_validate(r.model_dump()) for r in rows]
        return SessionListResponse(
            items=items, total=total, limit=limit, offset=offset
        )

    def get_session_detail(
        self,
        session_id: str,
        db: SQLSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> SessionDetail:
        """Return full session detail with events.

        Events are capped at the **last 1000** (most recent by ts) and
        returned in ts ASC order, per BACKEND-API-V0.md §4.3.
        """
        row = db.exec(
            select(SessionRow).where(SessionRow.id == session_id)
        ).first()
        # 404 (not 403) on cross-user to avoid leaking existence.
        if row is None or row.user != current_user:
            raise HTTPException(status_code=404, detail="session not found")

        # Fetch last 1000 events (ordered DESC, then reverse to ASC).
        recent = db.exec(
            select(Event)
            .where(Event.session_id == session_id)
            .order_by(Event.ts.desc())
            .limit(1000)
        ).all()
        events_asc = list(reversed(recent))

        events_out = _enrich_events(events_asc)
        return SessionDetail.model_validate(
            {**row.model_dump(), "events": events_out}
        )

    def get_session_trail(
        self,
        session_id: str,
        response: Response,
        db: SQLSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> TrailOut:
        """Compliance-audit export — full session + ALL events, no cap.

        Per BACKEND-API-V0.md §4.6. Sets Content-Disposition so `curl -OJ`
        saves as `receipt-{session_id}.json`.
        """
        row = db.exec(
            select(SessionRow).where(SessionRow.id == session_id)
        ).first()
        if row is None or row.user != current_user:
            raise HTTPException(status_code=404, detail="session not found")

        events = db.exec(
            select(Event)
            .where(Event.session_id == session_id)
            .order_by(Event.ts.asc())
        ).all()

        response.headers["Content-Disposition"] = (
            f'attachment; filename="receipt-{session_id}.json"'
        )
        return TrailOut(
            session=TrailSession.model_validate(row.model_dump()),
            events=_enrich_events(list(events)),
            exported_at=datetime.now(timezone.utc),
            schema_version="v0",
        )
