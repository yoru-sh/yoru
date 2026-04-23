"""Team dashboard router.

Contract: task api-team-dashboard-endpoint (PRODUCT.md §6). Aggregates
sessions per user within a time window.

Auth: bearer-token gated via `require_current_user`. Pre-hardening this
returned every user's email + session count + cost unauthenticated — a
real PII leak caught by the 2026-04-23 endpoint sweep.

Scope: results are narrowed to workspaces the caller has a session in
(proxy for "users who share a workspace with me"). A user solo on their
personal workspace sees only themselves. A user in an org sees teammates
who've actually run sessions there. Sessions with NULL workspace_id
(legacy, pre-routing) are treated as the caller's personal scope — they
see only their own legacy rows.
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
        current_user: str = Depends(require_current_user),
    ) -> TeamDashboardOut:
        since_dt = _naive_utc(since) if since is not None else _default_since()

        # Workspaces the caller has activity in. This is the "team" — anyone
        # else who's routed a session to one of these workspaces is visible.
        my_workspaces_stmt = (
            select(SessionRow.workspace_id)
            .where(SessionRow.user == current_user)
            .where(SessionRow.workspace_id.is_not(None))
            .distinct()
        )
        my_workspace_ids = [w for w in db.exec(my_workspaces_stmt).all() if w]

        # Always include the caller themselves — covers the solo-on-Free case
        # and legacy sessions where workspace_id is NULL.
        scope_filter = SessionRow.user == current_user
        if my_workspace_ids:
            scope_filter = scope_filter | SessionRow.workspace_id.in_(my_workspace_ids)

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
            .where(scope_filter)
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
