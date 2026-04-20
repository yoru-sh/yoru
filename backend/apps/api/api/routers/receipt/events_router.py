"""Events ingestion router for Receipt v0.

Contract: vault/BACKEND-API-V0.md §4.1. One batch = one DB transaction.
Idempotent: duplicate session_id merges aggregates onto the existing row.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
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

from apps.api.api.middlewares.metrics import receipt_events_ingested_total
from apps.api.core.logging import get_logger

from .db import get_session
from .deps import get_current_user
from .models import (
    Event,
    EventKind,
    EventsBatchIn,
    IngestAck,
    Session as SessionRow,
)
from .red_flags import scan_event
from .summary_router import _build_summary

# tool_name → kind classifier (closes gap #3; see vault/EVENTIN-V1-SPEC.md §2)
_FILE_CHANGE_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})


def _infer_kind(tool: str | None) -> EventKind:
    if tool in _FILE_CHANGE_TOOLS:
        return "file_change"
    return "tool_use"


class EventsRouter:
    """POST /sessions/events — batch ingest from the Claude Code hook."""

    def __init__(self) -> None:
        self.logger = LoggingController(app_name="receipt_events_router")
        self._log = get_logger("apps.api.receipt.events")
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
        current_user: str | None = Depends(get_current_user),
    ) -> IngestAck:
        """Persist a batch of events + update session aggregates atomically.

        User attribution: `event.user` wins when set (v0 trust-body contract,
        used by scripts/smoke-us14.sh). Otherwise the bearer-derived user
        from deps.get_current_user is used. If neither is present the batch
        is rejected 422 — closes the silent-ingest-zero-events failure mode
        (vault/audits/us14-activation-smoke.md §real-hook gap #1).
        """
        touched: dict[str, SessionRow] = {}
        flagged_ids: set[str] = set()
        accepted = 0

        self._log.info("events.received", extra={"batch_size": len(batch.events)})

        for e in batch.events:
            effective_user = e.user or current_user
            if effective_user is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "user attribution required: provide 'user' in event "
                        "body or an Authorization bearer token"
                    ),
                )
            ts = _naive_utc(e.ts)
            if e.kind is None:
                e.kind = _infer_kind(e.tool)
            # Extract path + content from raw.tool_input for all known tool shapes.
            # (EVENTIN-V1-SPEC §2.b for file_path; extended here for Bash/Grep/Read/WebSearch.)
            raw_input = (e.raw or {}).get("tool_input")
            if isinstance(raw_input, dict):
                if e.path is None:
                    p = raw_input.get("file_path") or raw_input.get("path") or raw_input.get("notebook_path")
                    if isinstance(p, str) and p:
                        e.path = p
                if e.content is None:
                    # Bash → command; Grep → pattern; Read → path (already captured); WebSearch/WebFetch → query/url
                    c = (
                        raw_input.get("command")
                        or raw_input.get("pattern")
                        or raw_input.get("query")
                        or raw_input.get("url")
                        or raw_input.get("old_string")
                        or raw_input.get("new_string")
                        or raw_input.get("content")
                    )
                    if isinstance(c, str) and c:
                        e.content = c[:400]  # cap at 400 chars for display
            flags = scan_event(e)

            sess = touched.get(e.session_id)
            if sess is None:
                sess = session.get(SessionRow, e.session_id)
                if sess is None:
                    sess = SessionRow(
                        id=e.session_id,
                        user=effective_user,
                        started_at=ts,
                    )
                    session.add(sess)
                    session.flush()
                touched[e.session_id] = sess

            if e.kind == "session_start":
                if ts < sess.started_at:
                    sess.started_at = ts
            elif e.kind == "session_end":
                pass
            elif e.kind == "tool_use":
                sess.tools_count += 1
                if e.tool and e.tool not in sess.tools_called:
                    sess.tools_called = [*sess.tools_called, e.tool]
            elif e.kind == "file_change" and e.path:
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
            receipt_events_ingested_total.labels(
                kind=e.kind or "unknown",
                flagged=str(bool(flags)).lower(),
            ).inc()
            accepted += 1

        session.commit()

        # Auto-summary on session_end: if any event in this batch marked a session
        # as ended and the session has no summary yet, build & persist the
        # deterministic 3-liner now so the frontend detail page doesn't 404.
        session_end_ids = {
            e.session_id for e in batch.events if e.kind == "session_end"
        }
        if session_end_ids:
            for sid in session_end_ids:
                sess = touched.get(sid) or session.get(SessionRow, sid)
                if sess is None or sess.summary is not None:
                    continue
                sess.summary = _build_summary(sess)
                session.add(sess)
            session.commit()

        self._log.info(
            "events.ingested",
            extra={
                "accepted": accepted,
                "sessions": len(touched),
                "flagged": len(flagged_ids),
            },
        )

        return IngestAck(
            accepted=accepted,
            session_ids=list(touched.keys()),
            flagged_sessions=sorted(flagged_ids),
        )
