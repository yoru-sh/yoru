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

        events_out = [EventOut.model_validate(e.model_dump()) for e in events_asc]
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
            events=[EventOut.model_validate(e.model_dump()) for e in events],
            exported_at=datetime.now(timezone.utc),
            schema_version="v0",
        )
