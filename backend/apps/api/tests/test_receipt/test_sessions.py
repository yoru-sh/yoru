"""Tests for Receipt v0 sessions list + detail (§4.2, §4.3).

Auth enforcement per AUTH-V0 §1(c): read routes require a bearer hook-token,
list is scoped to the token's user, detail returns 404 on cross-user.
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
    """Override conftest.app to mount only SessionsRouter.

    Lets this test module run independently of sibling devs (events_router,
    summary_router). The shared conftest version imports all three; once they
    land, either fixture gives identical behavior for our routes.
    """
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


def _seed_four_sessions(db_session) -> None:
    rows = [
        SessionRow(
            id="s1", user="alice",
            started_at=BASE_TS + timedelta(minutes=0),
            cost_usd=0.05, flagged=False, flags=[],
        ),
        SessionRow(
            id="s2", user="bob",
            started_at=BASE_TS + timedelta(minutes=10),
            cost_usd=0.50, flagged=True, flags=["secret_aws"],
        ),
        SessionRow(
            id="s3", user="alice",
            started_at=BASE_TS + timedelta(minutes=20),
            cost_usd=0.20, flagged=True, flags=["shell_rm"],
        ),
        SessionRow(
            id="s4", user="carol",
            started_at=BASE_TS + timedelta(minutes=30),
            cost_usd=1.00, flagged=False, flags=[],
        ),
    ]
    for r in rows:
        db_session.add(r)
    db_session.commit()


def test_list_scoped_to_current_user(client, db_session, alice_headers):
    _seed_four_sessions(db_session)
    resp = client.get("/api/v1/sessions", headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()
    # Only alice's 2 sessions are visible; bob + carol are scoped out.
    assert body["total"] == 2
    assert [i["id"] for i in body["items"]] == ["s3", "s1"]
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_filter_flagged_true(client, db_session, alice_headers):
    _seed_four_sessions(db_session)
    resp = client.get(
        "/api/v1/sessions", params={"flagged": "true"}, headers=alice_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    # Alice has 2 sessions, 1 is flagged (s3). bob's flagged s2 is filtered out.
    assert body["total"] == 1
    assert {i["id"] for i in body["items"]} == {"s3"}
    assert all(i["flagged"] is True for i in body["items"])


def test_filter_min_cost(client, db_session, mint_token):
    _seed_four_sessions(db_session)
    # Authenticate as carol (owns s4 @ $1.00) so min_cost=0.30 has a hit.
    _, carol_h = mint_token("carol")
    resp = client.get(
        "/api/v1/sessions", params={"min_cost": 0.30}, headers=carol_h
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert {i["id"] for i in body["items"]} == {"s4"}


def test_filter_date_range(client, db_session, alice_headers):
    _seed_four_sessions(db_session)
    params = {
        "from_ts": (BASE_TS + timedelta(minutes=5)).isoformat(),
        "to_ts": (BASE_TS + timedelta(minutes=25)).isoformat(),
    }
    resp = client.get("/api/v1/sessions", params=params, headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()
    # Alice's s3 @ +20 is the only session in the window for this user.
    assert body["total"] == 1
    assert {i["id"] for i in body["items"]} == {"s3"}


def test_pagination_limit_offset(client, db_session, mint_token):
    # Seed 4 sessions all owned by alice so pagination has enough rows.
    for i in range(4):
        db_session.add(SessionRow(
            id=f"p{i}", user="alice",
            started_at=BASE_TS + timedelta(minutes=i * 10),
            cost_usd=0.1 * (i + 1),
        ))
    db_session.commit()
    _, h = mint_token("alice")
    resp = client.get(
        "/api/v1/sessions", params={"limit": 2, "offset": 2}, headers=h
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4
    assert body["limit"] == 2
    assert body["offset"] == 2
    # DESC order is p3, p2, p1, p0 → offset=2 skips p3+p2, takes p1, p0.
    assert [i["id"] for i in body["items"]] == ["p1", "p0"]


def test_limit_capped_at_200(client, db_session, alice_headers):
    _seed_four_sessions(db_session)
    resp = client.get(
        "/api/v1/sessions", params={"limit": 201}, headers=alice_headers
    )
    # Pydantic Query(le=200) rejects >200.
    assert resp.status_code == 422


def test_detail_happy_path(client, db_session, alice_headers):
    db_session.add(SessionRow(
        id="sd1", user="alice",
        started_at=BASE_TS,
        ended_at=BASE_TS + timedelta(minutes=5),
        tools_count=3, files_count=2,
        tokens_input=100, tokens_output=50, cost_usd=0.12,
        flagged=True, flags=["secret_aws"],
        files_changed=["app.py", "README.md"],
        tools_called=["Bash", "Edit"],
        summary=None,
    ))
    # Seed events out-of-order to confirm server re-sorts ts ASC.
    db_session.add(Event(
        session_id="sd1",
        ts=BASE_TS + timedelta(seconds=2),
        kind="tool_use", tool="Edit", content="evt-2",
        flags=[],
    ))
    db_session.add(Event(
        session_id="sd1",
        ts=BASE_TS + timedelta(seconds=0),
        kind="tool_use", tool="Bash", content="evt-0",
        flags=["shell_rm"],
    ))
    db_session.add(Event(
        session_id="sd1",
        ts=BASE_TS + timedelta(seconds=1),
        kind="file_change", path="app.py", content="evt-1",
        flags=[],
    ))
    db_session.commit()

    resp = client.get("/api/v1/sessions/sd1", headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "sd1"
    assert body["files_changed"] == ["app.py", "README.md"]
    assert body["tools_called"] == ["Bash", "Edit"]
    assert body["flags"] == ["secret_aws"]
    assert body["summary"] is None
    # Events sorted ASC by ts.
    assert [e["content"] for e in body["events"]] == ["evt-0", "evt-1", "evt-2"]
    assert body["events"][0]["flags"] == ["shell_rm"]


def test_detail_404_on_unknown_id(client, alice_headers):
    resp = client.get("/api/v1/sessions/does-not-exist", headers=alice_headers)
    assert resp.status_code == 404


def test_detail_404_on_cross_user(client, db_session, alice_headers):
    """Alice asking for bob's session must get 404, not 403 (don't leak existence)."""
    _seed_four_sessions(db_session)
    resp = client.get("/api/v1/sessions/s2", headers=alice_headers)  # s2 = bob
    assert resp.status_code == 404


def test_list_401_without_bearer(client, db_session):
    _seed_four_sessions(db_session)
    resp = client.get("/api/v1/sessions")
    assert resp.status_code == 401


def test_detail_401_without_bearer(client, db_session):
    _seed_four_sessions(db_session)
    resp = client.get("/api/v1/sessions/s1")
    assert resp.status_code == 401


def test_detail_events_enriched_fields(client, db_session, alice_headers):
    """3-event session returns EventOut entries with group_key + duration_ms."""
    db_session.add(SessionRow(id="en1", user="alice", started_at=BASE_TS))
    db_session.add(Event(
        session_id="en1",
        ts=BASE_TS + timedelta(seconds=0),
        kind="tool_use", tool="Bash", flags=[],
        raw={"tool_name": "Bash", "tool_input": {"command": "ls -la /tmp"}},
    ))
    db_session.add(Event(
        session_id="en1",
        ts=BASE_TS + timedelta(seconds=1),
        kind="tool_use", tool="Read", flags=[],
        raw={"tool_input": {"file_path": "/Users/x/README.md"}},
    ))
    db_session.add(Event(
        session_id="en1",
        ts=BASE_TS + timedelta(seconds=3),
        kind="tool_use", tool="Edit", flags=[],
        raw={"tool_input": {"file_path": "/Users/x/app.py", "old_string": "foo"}},
    ))
    db_session.commit()

    resp = client.get("/api/v1/sessions/en1", headers=alice_headers)
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) == 3
    for e in events:
        assert e["group_key"]
    assert events[0]["tool"] == "Bash"
    assert events[0]["path"] == "ls -la /tmp"
    assert events[0]["content"] == "ls -la /tmp"
    assert events[0]["duration_ms"] == 1000
    assert events[1]["tool"] == "Read"
    assert events[1]["path"] == "/Users/x/README.md"
    assert events[1]["duration_ms"] == 2000
    assert events[2]["duration_ms"] is None


def test_session_end_triggers_auto_summary(engine, db_session, mint_token):
    """Ingest batch with kind='session_end' → /summary returns 200 (not 404)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlmodel import Session as SQLSession

    from apps.api.api.routers.receipt.db import get_session
    from apps.api.api.routers.receipt.events_router import EventsRouter
    from apps.api.api.routers.receipt.summary_router import SummaryRouter

    _app = FastAPI()
    _app.include_router(EventsRouter().get_router(), prefix="/api/v1")
    _app.include_router(SummaryRouter().get_router(), prefix="/api/v1")

    def _override():
        with SQLSession(engine) as s:
            yield s

    _app.dependency_overrides[get_session] = _override
    c = TestClient(_app)

    _, h = mint_token("alice")
    batch = {
        "events": [
            {
                "session_id": "ae1",
                "user": "alice",
                "kind": "tool_use",
                "tool": "Bash",
                "ts": BASE_TS.isoformat(),
            },
            {
                "session_id": "ae1",
                "user": "alice",
                "kind": "session_end",
                "ts": (BASE_TS + timedelta(seconds=5)).isoformat(),
            },
        ]
    }
    ing = c.post("/api/v1/sessions/events", json=batch)
    assert ing.status_code == 202

    resp = c.get("/api/v1/sessions/ae1/summary", headers=h)
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "ae1"
    assert body["summary"].count("\n") == 2  # 3-line determinstic summary


def test_detail_event_cap(client, db_session, alice_headers):
    """1005 events seeded → response returns the 1000 most recent, ASC.

    Contract (§4.3): "Events ordered ts ASC, capped at last 1000". We fetch
    the newest 1000 via ts DESC + LIMIT 1000 and reverse to ASC, so the
    oldest 5 events are dropped and the payload is evt-5 … evt-1004.
    """
    db_session.add(SessionRow(id="cap", user="alice", started_at=BASE_TS))
    for i in range(1005):
        db_session.add(Event(
            session_id="cap",
            ts=BASE_TS + timedelta(seconds=i),
            kind="tool_use", tool="Bash", content=f"evt-{i}",
            flags=[],
        ))
    db_session.commit()

    resp = client.get("/api/v1/sessions/cap", headers=alice_headers)
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) == 1000
    assert events[0]["content"] == "evt-5"
    assert events[-1]["content"] == "evt-1004"
