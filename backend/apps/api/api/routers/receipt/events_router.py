"""Events ingestion router for Receipt v0.

Contract: vault/BACKEND-API-V0.md §4.1. One batch = one DB transaction.
Idempotent: duplicate session_id merges aggregates onto the existing row.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlmodel import Session as DBSession


def _naive_utc(d: datetime | None) -> datetime:
    """Normalize to naive UTC — SQLite drops tzinfo so everything in the
    DB is naive; inputs may be aware. Unifying here prevents aware/naive
    comparison errors when merging aggregates across batches."""
    if d is None:
        d = datetime.now(timezone.utc)
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d

from libs.log_manager.controller import LoggingController

from .db import get_session
from .models import (
    Event,
    EventsBatchIn,
    IngestAck,
    Session as SessionRow,
)
from .red_flags import scan_event


class EventsRouter:
    """POST /sessions/events — batch ingest from the Claude Code hook."""

    def __init__(self) -> None:
        self.logger = LoggingController(app_name="receipt_events_router")
        self.router = APIRouter(prefix="/sessions", tags=["receipt:events"])
        self._setup_routes()
        self.logger.log_info("Receipt events router initialized")

    def get_router(self) -> APIRouter:
        return self.router

    def initialize_services(self) -> None:
        pass

    def _setup_routes(self) -> None:
        self.router.post(
            "/events",
            response_model=IngestAck,
            status_code=status.HTTP_202_ACCEPTED,
        )(self.ingest)

    def ingest(
        self,
        batch: EventsBatchIn,
        session: DBSession = Depends(get_session),
    ) -> IngestAck:
        """Persist a batch of events + update session aggregates atomically."""
        touched: dict[str, SessionRow] = {}
        flagged_ids: set[str] = set()
        accepted = 0

        for e in batch.events:
            ts = _naive_utc(e.ts)
            flags = scan_event(e)

            sess = touched.get(e.session_id)
            if sess is None:
                sess = session.get(SessionRow, e.session_id)
                if sess is None:
                    sess = SessionRow(
                        id=e.session_id,
                        user=e.user,
                        started_at=ts,
                    )
                    session.add(sess)
                    session.flush()
                touched[e.session_id] = sess

            if e.kind == "tool_use":
                sess.tools_count += 1
                if e.tool and e.tool not in sess.tools_called:
                    sess.tools_called = [*sess.tools_called, e.tool]
            if e.kind == "file_change" and e.path:
                if e.path not in sess.files_changed:
                    sess.files_count += 1
                    sess.files_changed = [*sess.files_changed, e.path]

            sess.tokens_input += e.tokens_input
            sess.tokens_output += e.tokens_output
            sess.cost_usd += e.cost_usd
            if sess.ended_at is None or ts > sess.ended_at:
                sess.ended_at = ts

            if flags:
                merged = list(sess.flags)
                for f in flags:
                    if f not in merged:
                        merged.append(f)
                sess.flags = merged
                sess.flagged = True
                flagged_ids.add(sess.id)

            session.add(
                Event(
                    session_id=e.session_id,
                    ts=ts,
                    kind=e.kind,
                    tool=e.tool,
                    path=e.path,
                    content=e.content,
                    tokens_input=e.tokens_input,
                    tokens_output=e.tokens_output,
                    cost_usd=e.cost_usd,
                    flags=flags,
                    raw=e.raw,
                )
            )
            accepted += 1

        session.commit()

        return IngestAck(
            accepted=accepted,
            session_ids=list(touched.keys()),
            flagged_sessions=sorted(flagged_ids),
        )
