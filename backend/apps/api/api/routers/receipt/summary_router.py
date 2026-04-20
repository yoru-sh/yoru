"""Summary stub router for Receipt v0.

Contract: vault/BACKEND-API-V0.md §4.4 + §4.5. Deterministic 3-line string,
no LLM call. Persists to Session.summary; re-POST overwrites.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session as DBSession, select

from libs.log_manager.controller import LoggingController

from .db import get_session
from .deps import require_current_user
from .models import (
    Event,
    Session as SessionRow,
    SummaryOut,
)


def _duration_seconds(started_at: datetime | None, ended_at: datetime | None) -> int:
    if started_at is None or ended_at is None:
        return 0
    return int((ended_at - started_at).total_seconds())


def _build_summary(sess: SessionRow) -> str:
    """Render the deterministic 3-line Receipt per BACKEND-API-V0.md §4.4."""
    duration = _duration_seconds(sess.started_at, sess.ended_at)
    line1 = (
        f"{sess.tools_count} tools across {sess.files_count} files "
        f"in {duration}s."
    )
    line2 = (
        f"Tokens: {sess.tokens_input}→{sess.tokens_output}  "
        f"Cost: ${sess.cost_usd:.2f}."
    )
    flags: Sequence[str] = list(sess.flags or [])
    line3 = f"Flags: {', '.join(flags)}." if flags else "Flags: none."
    return "\n".join([line1, line2, line3])


class SummaryRouter:
    """POST/GET /sessions/{session_id}/summary — deterministic Receipt stub."""

    def __init__(self) -> None:
        self.logger = LoggingController(app_name="receipt_summary_router")
        self.router = APIRouter(prefix="/sessions", tags=["receipt:summary"])
        self._setup_routes()
        self.logger.log_info("Receipt summary router initialized")

    def get_router(self) -> APIRouter:
        return self.router

    def initialize_services(self) -> None:
        pass

    def _setup_routes(self) -> None:
        self.router.post(
            "/{session_id}/summary",
            response_model=SummaryOut,
            status_code=status.HTTP_200_OK,
        )(self.generate)
        self.router.get(
            "/{session_id}/summary",
            response_model=SummaryOut,
        )(self.retrieve)

    def generate(
        self,
        session_id: str,
        session: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> SummaryOut:
        sess = session.get(SessionRow, session_id)
        # 404 (not 403) on cross-user to avoid leaking existence.
        if sess is None or sess.user != current_user:
            raise HTTPException(status_code=404, detail="session not found")

        # §4.4 step 1: load up to last 50 events. Unused by the stub but
        # kept so the v1 LLM swap only touches _build_summary.
        session.exec(
            select(Event)
            .where(Event.session_id == session_id)
            .order_by(Event.ts.desc())
            .limit(50)
        ).all()

        summary = _build_summary(sess)
        sess.summary = summary
        session.add(sess)
        session.commit()

        return SummaryOut(
            session_id=session_id,
            summary=summary,
            generated_at=datetime.now(timezone.utc),
        )

    def retrieve(
        self,
        session_id: str,
        session: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> SummaryOut:
        sess = session.get(SessionRow, session_id)
        # 404 on unknown OR cross-user to avoid leaking existence.
        if sess is None or sess.user != current_user or sess.summary is None:
            raise HTTPException(status_code=404, detail="summary not found")
        return SummaryOut(
            session_id=session_id,
            summary=sess.summary,
            generated_at=datetime.now(timezone.utc),
        )
