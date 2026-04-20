"""Integration tests for POST /api/v1/sessions/events.

Depends on the `client` fixture from conftest.py which mounts all three
receipt routers. Run once sibling devs land sessions_router + summary_router.
"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session as DBSession, select

from apps.api.api.routers.receipt.models import Event, Session as SessionRow


def _event(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "s-1",
        "user": "u-1",
        "kind": "tool_use",
        "tool": "Edit",
        "content": "noop",
    }
    base.update(overrides)
    return base


def test_happy_path_batch(client: TestClient, engine) -> None:
    events = [
        _event(
            session_id="s-1",
            kind="tool_use",
            tool=f"Tool{i % 3}",
            tokens_input=2,
            tokens_output=3,
            cost_usd=0.01,
        )
        for i in range(10)
    ]
    resp = client.post("/api/v1/sessions/events", json={"events": events})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["accepted"] == 10
    assert body["session_ids"] == ["s-1"]
    assert body["flagged_sessions"] == []

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "s-1")
    assert sess is not None
    assert sess.tools_count == 10
    assert sess.tokens_input == 20
    assert sess.tokens_output == 30
    assert abs(sess.cost_usd - 0.10) < 1e-6
    assert sess.flagged is False
    # 3 distinct tool names deduped into tools_called
    assert sorted(sess.tools_called) == ["Tool0", "Tool1", "Tool2"]


def test_empty_batch_returns_422(client: TestClient) -> None:
    resp = client.post("/api/v1/sessions/events", json={"events": []})
    assert resp.status_code == 422


def test_oversize_batch_returns_422(client: TestClient) -> None:
    events = [_event(session_id="s-1") for _ in range(1001)]
    resp = client.post("/api/v1/sessions/events", json={"events": events})
    assert resp.status_code == 422


def test_mixed_session_batch_creates_both(client: TestClient, engine) -> None:
    events = [
        _event(session_id="s-A", tool="Bash"),
        _event(session_id="s-B", tool="Edit"),
        _event(session_id="s-A", tool="Read"),
    ]
    resp = client.post("/api/v1/sessions/events", json={"events": events})
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 3
    assert sorted(body["session_ids"]) == ["s-A", "s-B"]

    with DBSession(engine) as s:
        sa = s.get(SessionRow, "s-A")
        sb = s.get(SessionRow, "s-B")
    assert sa is not None and sb is not None
    assert sa.tools_count == 2
    assert sb.tools_count == 1


def test_flag_propagation_aws_key(client: TestClient, engine) -> None:
    events = [
        _event(
            session_id="s-leak",
            kind="tool_use",
            tool="Bash",
            content="export AWS_KEY=AKIAIOSFODNN7EXAMPLE",
        )
    ]
    resp = client.post("/api/v1/sessions/events", json={"events": events})
    assert resp.status_code == 202
    body = resp.json()
    assert body["flagged_sessions"] == ["s-leak"]

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "s-leak")
    assert sess is not None
    assert sess.flagged is True
    assert "secret_aws" in sess.flags


def test_file_change_aggregates_and_dedupes(client: TestClient, engine) -> None:
    events = [
        _event(session_id="s-f", kind="file_change", tool=None, path="a.py"),
        _event(session_id="s-f", kind="file_change", tool=None, path="a.py"),
        _event(session_id="s-f", kind="file_change", tool=None, path="b.py"),
    ]
    resp = client.post("/api/v1/sessions/events", json={"events": events})
    assert resp.status_code == 202

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "s-f")
    assert sess is not None
    assert sess.files_count == 2
    assert sorted(sess.files_changed) == ["a.py", "b.py"]


def test_idempotent_session_update_across_requests(
    client: TestClient, engine
) -> None:
    first = [_event(session_id="s-dup", tool="Bash", tokens_input=5)]
    second = [_event(session_id="s-dup", tool="Edit", tokens_input=7)]

    r1 = client.post("/api/v1/sessions/events", json={"events": first})
    r2 = client.post("/api/v1/sessions/events", json={"events": second})
    assert r1.status_code == 202 and r2.status_code == 202

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "s-dup")
    assert sess is not None
    assert sess.tools_count == 2
    assert sess.tokens_input == 12
    assert sorted(sess.tools_called) == ["Bash", "Edit"]


# ---------- bearer-derived user attribution (gap-3 fix) ----------


def test_user_derived_from_bearer_when_body_user_absent(
    client: TestClient, engine, mint_token
) -> None:
    """Event without body.user + valid bearer → 202, session attributed to bearer.user."""
    _, headers = mint_token("alice@example.com")
    event = {
        "session_id": "s-bearer",
        "kind": "tool_use",
        "tool": "Edit",
        "content": "noop",
    }
    resp = client.post(
        "/api/v1/sessions/events",
        json={"events": [event]},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["session_ids"] == ["s-bearer"]

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "s-bearer")
    assert sess is not None
    assert sess.user == "alice@example.com"


def test_user_absent_and_no_bearer_is_rejected(client: TestClient) -> None:
    """Event without body.user AND no bearer → 422 (no way to attribute)."""
    event = {
        "session_id": "s-noone",
        "kind": "tool_use",
        "tool": "Edit",
        "content": "noop",
    }
    resp = client.post("/api/v1/sessions/events", json={"events": [event]})
    assert resp.status_code == 422, resp.text
    assert "user" in resp.text.lower()


def test_body_user_wins_over_bearer(
    client: TestClient, engine, mint_token
) -> None:
    """v0 contract: body.user is trusted when set, even alongside a bearer.

    Preserves scripts/smoke-us14.sh behavior; tightening to bearer-always is
    a v1 concern (see USER_STORIES §US-20 org-scoping).
    """
    _, headers = mint_token("alice@example.com")
    resp = client.post(
        "/api/v1/sessions/events",
        json={"events": [_event(session_id="s-both", user="bob@example.com")]},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    with DBSession(engine) as s:
        sess = s.get(SessionRow, "s-both")
    assert sess is not None
    assert sess.user == "bob@example.com"


# ---------- kind classifier (gap-3 fix) ----------


def test_kind_inferred_as_file_change_for_write_toolname(
    client: TestClient, engine, mint_token
) -> None:
    """POST with no `kind` + `tool_name="Write"` → 202; stored Event.kind == file_change."""
    _, headers = mint_token("alice@example.com")
    event = {
        "session_id": "gap3-write",
        "tool_name": "Write",
        "content": "hello",
    }
    resp = client.post(
        "/api/v1/sessions/events",
        json={"events": [event]},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["session_ids"] == ["gap3-write"]

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "gap3-write")
        rows = s.exec(
            select(Event).where(Event.session_id == "gap3-write")
        ).all()
    assert sess is not None
    assert sess.user == "alice@example.com"
    assert len(rows) == 1
    assert rows[0].kind == "file_change"
    assert rows[0].tool == "Write"


def test_session_start_creates_row_without_tool_counts(
    client: TestClient, engine
) -> None:
    """session_start event creates a session row with tools_count=0, files_count=0."""
    ts = "2026-04-20T10:00:00+00:00"
    events = [
        {
            "session_id": "lc-start-1",
            "user": "u-1",
            "kind": "session_start",
            "ts": ts,
        }
    ]
    resp = client.post("/api/v1/sessions/events", json={"events": events})
    assert resp.status_code == 202, resp.text

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "lc-start-1")
    assert sess is not None
    assert sess.tools_count == 0
    assert sess.files_count == 0
    from datetime import datetime
    expected = datetime.fromisoformat(ts).replace(tzinfo=None)
    assert sess.started_at == expected


def test_session_end_updates_ended_at(client: TestClient, engine) -> None:
    """session_end event updates ended_at without incrementing tools/files counts."""
    start_ts = "2026-04-20T10:00:00+00:00"
    end_ts = "2026-04-20T10:05:00+00:00"
    events = [
        {
            "session_id": "lc-end-1",
            "user": "u-1",
            "kind": "session_start",
            "ts": start_ts,
        },
        {
            "session_id": "lc-end-1",
            "user": "u-1",
            "kind": "session_end",
            "ts": end_ts,
        },
    ]
    resp = client.post("/api/v1/sessions/events", json={"events": events})
    assert resp.status_code == 202, resp.text

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "lc-end-1")
    assert sess is not None
    assert sess.tools_count == 0
    assert sess.files_count == 0
    from datetime import datetime
    expected = datetime.fromisoformat(end_ts).replace(tzinfo=None)
    assert sess.ended_at == expected


def test_file_path_extracted_from_raw_tool_input(
    client: TestClient, engine, mint_token
) -> None:
    """Edit/Write/NotebookEdit with no top-level `path` but `raw.tool_input.file_path`
    set → each persists as kind=file_change with path populated, and the parent
    session aggregates files_changed + files_count across all three.
    """
    _, headers = mint_token("alice@example.com")
    events = [
        {
            "session_id": "raw-paths",
            "tool_name": "Edit",
            "raw": {"tool_input": {"file_path": "/tmp/a.py"}},
        },
        {
            "session_id": "raw-paths",
            "tool_name": "Write",
            "raw": {"tool_input": {"file_path": "/tmp/b.py"}},
        },
        {
            "session_id": "raw-paths",
            "tool_name": "NotebookEdit",
            "raw": {"tool_input": {"file_path": "/tmp/c.ipynb"}},
        },
    ]
    resp = client.post(
        "/api/v1/sessions/events",
        json={"events": events},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "raw-paths")
        rows = s.exec(
            select(Event).where(Event.session_id == "raw-paths").order_by(Event.id)
        ).all()
    assert sess is not None
    assert len(rows) == 3
    assert [r.kind for r in rows] == ["file_change", "file_change", "file_change"]
    assert [r.path for r in rows] == ["/tmp/a.py", "/tmp/b.py", "/tmp/c.ipynb"]
    assert sess.files_count == 3
    assert sorted(sess.files_changed) == ["/tmp/a.py", "/tmp/b.py", "/tmp/c.ipynb"]


def test_kind_inferred_as_tool_use_for_bash_toolname(
    client: TestClient, engine, mint_token
) -> None:
    """POST with no `kind` + `tool_name="Bash"` → 202; stored Event.kind == tool_use."""
    _, headers = mint_token("alice@example.com")
    event = {
        "session_id": "gap3-bash",
        "tool_name": "Bash",
        "content": "ls -la",
    }
    resp = client.post(
        "/api/v1/sessions/events",
        json={"events": [event]},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["session_ids"] == ["gap3-bash"]

    with DBSession(engine) as s:
        sess = s.get(SessionRow, "gap3-bash")
        rows = s.exec(
            select(Event).where(Event.session_id == "gap3-bash")
        ).all()
    assert sess is not None
    assert len(rows) == 1
    assert rows[0].kind == "tool_use"
    assert rows[0].tool == "Bash"
