"""Wave-12 E4 — team dashboard rollup + summary persistence integration tests.

Covers:
  - case #4: two users, four sessions total — GET /dashboard/team returns
             per-user aggregates + totals across ALL sessions in the window.
  - case #6: POST→GET→re-POST on /sessions/{id}/summary confirms the
             deterministic 3-line template persists and is idempotent.

Contract refs: BACKEND-API-V0.md §4.4–§4.5 (summary), §6 / dashboard_router.py
(team). Dashboard has NO auth in v0 (see dashboard_router.py note re: follow-up
ticket d2883124); it is global-scope, not caller-scoped, so the test relies on
clean_db truncating the sessions table and bounding the `since` window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# Force SQLModel metadata registration so the autouse `clean_db` fixture in
# conftest.py can resolve the "events"/"sessions"/"hook_tokens" tables when
# THIS module is run in isolation (`pytest <this-file>`). Without this, the
# conftest's `SQLModel.metadata.tables.get(name)` returns None and truncation
# silently no-ops → prior-run state leaks across tests.
from apps.api.api.routers.receipt import models  # noqa: F401


@pytest.mark.integration
async def test_dashboard_team_per_user_aggregates(client, clean_db):
    # Two distinct hook-tokens for two distinct users.
    user_a = "team-a@test.local"
    user_b = "team-b@test.local"

    mint_a = await client.post("/api/v1/auth/hook-token", json={"user": user_a})
    assert mint_a.status_code == 201, mint_a.text
    token_a = mint_a.json()["token"]

    mint_b = await client.post("/api/v1/auth/hook-token", json={"user": user_b})
    assert mint_b.status_code == 201, mint_b.text
    token_b = mint_b.json()["token"]

    # `since` must be BEFORE any session we're about to create.
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    # 3 events per user spread across 2 sessions each → 4 sessions, 6 events.
    # user A: session a-1 (2 events) + a-2 (1 event). Same shape for B.
    async def _post(token: str, events: list[dict]) -> None:
        r = await client.post(
            "/api/v1/sessions/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"events": events},
        )
        assert r.status_code == 202, r.text

    await _post(
        token_a,
        [
            {"session_id": "sess-a-1", "tool_name": "Bash", "content": "ls"},
            {"session_id": "sess-a-1", "tool_name": "Read", "content": "cat x"},
            {"session_id": "sess-a-2", "tool_name": "Bash", "content": "pwd"},
        ],
    )
    await _post(
        token_b,
        [
            {"session_id": "sess-b-1", "tool_name": "Bash", "content": "ls"},
            {"session_id": "sess-b-1", "tool_name": "Read", "content": "cat y"},
            {"session_id": "sess-b-2", "tool_name": "Bash", "content": "pwd"},
        ],
    )

    resp = await client.get("/api/v1/dashboard/team", params={"since": since})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Dashboard is NOT caller-scoped in v0 — filter by the two users we seeded.
    # clean_db truncates so the window should only hold our rows, but filtering
    # defensively makes the test robust against a parallel ingest on the live
    # backend during the run.
    by_email = {u["email"]: u for u in body["users"] if u["email"] in (user_a, user_b)}
    assert set(by_email.keys()) == {user_a, user_b}, body

    assert by_email[user_a]["sessions"] == 2
    assert by_email[user_b]["sessions"] == 2

    # totals.sessions is the canonical scalar (see dashboard_router.py §TeamDashboardTotals).
    # clean_db + a 1-minute `since` window guarantees no foreign rows.
    assert body["totals"]["sessions"] == 4, body["totals"]

    # Cross-check event count via per-user /sessions listing (dashboard schema
    # doesn't expose total_events; the user-filtered list is the nearest
    # canonical counter for the integration assertion).
    list_a = await client.get(
        "/api/v1/sessions",
        params={"user": user_a},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert list_a.status_code == 200, list_a.text
    items_a = list_a.json()["items"]
    assert sum(s["tools_count"] for s in items_a) == 3  # 3 non-file_change events

    list_b = await client.get(
        "/api/v1/sessions",
        params={"user": user_b},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert list_b.status_code == 200, list_b.text
    items_b = list_b.json()["items"]
    assert sum(s["tools_count"] for s in items_b) == 3


@pytest.mark.integration
async def test_summary_generate_persists_and_retrieves(authed_client):
    client, _user, _token = authed_client
    session_id = "sess-summ-01"

    # 5 events: 3 tool_use + 2 file_change (Write + Edit are classified as
    # file_change per events_router._FILE_CHANGE_TOOLS).
    ingest = await client.post(
        "/api/v1/sessions/events",
        json={
            "events": [
                {"session_id": session_id, "tool_name": "Bash", "content": "ls"},
                {"session_id": session_id, "tool_name": "Read", "content": "cat x"},
                {"session_id": session_id, "tool_name": "Write",
                 "path": "src/a.py", "content": "def a():\n    pass"},
                {"session_id": session_id, "tool_name": "Edit",
                 "path": "src/b.py", "content": "def b():\n    pass"},
                {"session_id": session_id, "tool_name": "Bash", "content": "pwd"},
            ]
        },
    )
    assert ingest.status_code == 202, ingest.text

    # POST → 200 with 3-line deterministic summary.
    gen = await client.post(f"/api/v1/sessions/{session_id}/summary")
    assert gen.status_code == 200, gen.text
    gen_body = gen.json()
    assert gen_body["session_id"] == session_id
    summary_text = gen_body["summary"]
    lines = summary_text.split("\n")
    assert len(lines) == 3, summary_text
    # Line 2 starts with "Tokens:" per §4.4; line 3 starts with "Flags:".
    assert lines[1].startswith("Tokens:"), summary_text
    assert lines[2].startswith("Flags:"), summary_text

    # GET returns byte-equal persisted text.
    got = await client.get(f"/api/v1/sessions/{session_id}/summary")
    assert got.status_code == 200, got.text
    assert got.json()["summary"] == summary_text

    # Re-POST is idempotent: 200, and regenerates (may be byte-equal since
    # template is deterministic over the unchanged session state).
    regen = await client.post(f"/api/v1/sessions/{session_id}/summary")
    assert regen.status_code == 200, regen.text
    regen_lines = regen.json()["summary"].split("\n")
    assert len(regen_lines) == 3
    assert regen_lines[1].startswith("Tokens:")
    assert regen_lines[2].startswith("Flags:")
