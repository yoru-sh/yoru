"""Tests for the trail export endpoint — §4.9 / SBA:2 Cleo persona.

`GET /api/v1/sessions/{session_id}/trail` returns a single-document JSON
receipt (session envelope + ALL events, no 1000 cap) + Content-Disposition
header + schema_version/exported_at metadata.

Auth (AUTH-V0 §1(c)):
  - 401 without a bearer
  - 404 on unknown id OR cross-user (collapsed guard, never 403)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlmodel import Session as SQLSession

from apps.api.api.routers.receipt.models import Event
from apps.api.api.routers.receipt.models import Session as SessionRow


BASE_TS = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def app(engine) -> FastAPI:
    """Mount only SessionsRouter so this module runs independently of siblings."""
    from apps.api.api.routers.receipt.db import get_session
    from apps.api.api.routers.receipt.sessions_router import SessionsRouter

    _app = FastAPI()
    _app.include_router(SessionsRouter().get_router(), prefix="/api/v1")

    def _override():
        with SQLSession(engine) as s:
            yield s

    _app.dependency_overrides[get_session] = _override
    return _app


@pytest.fixture()
def alice_headers(mint_token):
    _, h = mint_token("alice")
    return h


def _seed_bob_session(db_session) -> None:
    """Seed one session owned by bob — fixture for cross-user tests."""
    db_session.add(SessionRow(
        id="bob-s1", user="bob",
        started_at=BASE_TS,
        cost_usd=0.10, flagged=False, flags=[],
    ))
    db_session.commit()


def test_trail_happy_path_returns_all_events(client, db_session, alice_headers):
    """1100 events seeded — trail returns ALL of them, ASC, no cap."""
    db_session.add(SessionRow(
        id="tr1", user="alice",
        started_at=BASE_TS,
        ended_at=BASE_TS + timedelta(minutes=3),
        tools_count=2, files_count=1,
        tokens_input=10, tokens_output=5, cost_usd=0.04,
        flagged=True, flags=["shell_rm"],
        files_changed=["app.py"], tools_called=["Bash", "Edit"],
        summary="test",
    ))
    for i in range(1100):
        db_session.add(Event(
            session_id="tr1",
            ts=BASE_TS + timedelta(seconds=i),
            kind="tool_use", tool="Bash", content=f"evt-{i}",
            flags=[],
        ))
    db_session.commit()

    resp = client.get("/api/v1/sessions/tr1/trail", headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["schema_version"] == "v0"
    assert body["exported_at"].endswith(("Z", "+00:00"))
    # Session envelope carries detail fields; events live at envelope root only.
    assert body["session"]["id"] == "tr1"
    assert body["session"]["files_changed"] == ["app.py"]
    assert body["session"]["tools_called"] == ["Bash", "Edit"]
    assert body["session"]["summary"] == "test"
    assert "events" not in body["session"]
    # All 1100 events present, chronological ASC.
    assert len(body["events"]) == 1100
    assert body["events"][0]["content"] == "evt-0"
    assert body["events"][-1]["content"] == "evt-1099"


def test_trail_content_disposition_header(client, db_session, alice_headers):
    """Content-Disposition: attachment; filename=receipt-{session_id}.json."""
    db_session.add(SessionRow(id="tr2", user="alice", started_at=BASE_TS))
    db_session.commit()

    resp = client.get("/api/v1/sessions/tr2/trail", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == (
        'attachment; filename="receipt-tr2.json"'
    )


def test_trail_404_on_unknown_id(client, alice_headers):
    resp = client.get("/api/v1/sessions/does-not-exist/trail", headers=alice_headers)
    assert resp.status_code == 404


def test_trail_404_on_cross_user(client, db_session, alice_headers):
    """Alice reading bob's trail must 404, not 403 (don't leak existence)."""
    _seed_bob_session(db_session)
    resp = client.get("/api/v1/sessions/bob-s1/trail", headers=alice_headers)
    assert resp.status_code == 404


def test_trail_401_without_bearer(client, db_session):
    _seed_bob_session(db_session)
    resp = client.get("/api/v1/sessions/bob-s1/trail")
    assert resp.status_code == 401
