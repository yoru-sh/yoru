"""Integration tests for POST /api/v1/sessions/events.

Depends on the `client` fixture from conftest.py which mounts all three
receipt routers. Run once sibling devs land sessions_router + summary_router.
"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session as DBSession

from apps.api.api.routers.receipt.models import Session as SessionRow


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
