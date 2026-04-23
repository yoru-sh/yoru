"""Team dashboard router.

Contract: task api-team-dashboard-endpoint (PRODUCT.md §6). Aggregates
sessions per user within a time window.

Auth: bearer-token gated via `require_current_user`. Pre-hardening this
returned every user's email + session count + cost unauthenticated — a
real PII leak caught by the 2026-04-23 endpoint sweep.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import Session as SQLSession, select

from .db import get_session
from .deps import require_current_user
from .models import (
    Session as SessionRow,
    TeamDashboardOut,
    TeamDashboardTotals,
    TeamDashboardUser,
)


def _naive_utc(d: datetime) -> datetime:
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


def _default_since() -> datetime:
    return _naive_utc(datetime.now(timezone.utc) - timedelta(days=7))


class DashboardRouter:
    """GET /dashboard/team — per-user session aggregates."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/dashboard", tags=["receipt:dashboard"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.get("/team", response_model=TeamDashboardOut)(self.team)

    def team(
        self,
        since: Optional[datetime] = Query(default=None),
        db: SQLSession = Depends(get_session),
        _user: str = Depends(require_current_user),
    ) -> TeamDashboardOut:
        since_dt = _naive_utc(since) if since is not None else _default_since()

        group_stmt = (
            select(
                SessionRow.user,
                func.count().label("sessions"),
                func.coalesce(func.sum(SessionRow.flagged), 0).label("flagged"),
                func.coalesce(func.sum(SessionRow.cost_usd), 0.0).label(
                    "total_cost_usd"
                ),
            )
            .where(SessionRow.started_at >= since_dt)
            .group_by(SessionRow.user)
            .order_by(SessionRow.user)
        )
        rows = db.exec(group_stmt).all()

        users = [
            TeamDashboardUser(
                email=r.user,
                sessions=int(r.sessions),
                flagged=int(r.flagged or 0),
                total_cost_usd=float(r.total_cost_usd or 0.0),
            )
            for r in rows
        ]
        total_sessions = sum(u.sessions for u in users)
        total_flagged = sum(u.flagged for u in users)
        flagged_pct = (total_flagged / total_sessions) if total_sessions else 0.0

        return TeamDashboardOut(
            users=users,
            totals=TeamDashboardTotals(
                sessions=total_sessions,
                flagged=total_flagged,
                flagged_pct=flagged_pct,
            ),
        )
