"""Wave-12 E2 — auth + ingest happy-path integration tests.

Covers:
  - case #1: mint a hook-token then use it as a bearer on /sessions/events
  - case #2: ingest real-Claude-shape events (no `user`, no `kind` —
             server infers both) and verify aggregates on the detail view
             (gap #3 regression).

Contract refs: BACKEND-API-V0.md §4.1 (events), §4.3 (detail),
§4.6 (hook-token mint); models.py §EventIn (user/kind Optional + tool_name
alias).
"""
from __future__ import annotations

import pytest


@pytest.mark.integration
async def test_hook_token_mint_and_use(client, clean_db):
    mint = await client.post(
        "/api/v1/auth/hook-token",
        json={"user": "happy-01@test.local"},
    )
    assert mint.status_code == 201, mint.text
    mint_body = mint.json()
    token = mint_body["token"]
    assert token.startswith("rcpt_")
    assert mint_body["user_id"]
    assert mint_body["user"] == "happy-01@test.local"

    ingest = await client.post(
        "/api/v1/sessions/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "session_id": "sess-happy-01",
                    "user": "happy-01@test.local",
                    "kind": "tool_use",
                    "tool": "Bash",
                    "content": "echo hi",
                }
            ]
        },
    )
    assert ingest.status_code == 202, ingest.text
    body = ingest.json()
    assert body["accepted"] >= 1
    assert "sess-happy-01" in body["session_ids"]


@pytest.mark.integration
async def test_ingest_real_claude_shape_no_kind_no_user(authed_client):
    client, user, _token = authed_client

    ingest = await client.post(
        "/api/v1/sessions/events",
        json={
            "events": [
                {
                    "session_id": "sess-happy-02",
                    "tool_name": "Write",
                    "content": "def foo():\n    pass",
                    "path": "src/foo.py",
                },
                {
                    "session_id": "sess-happy-02",
                    "tool_name": "Bash",
                    "content": "ls",
                },
            ]
        },
    )
    assert ingest.status_code == 202, ingest.text
    assert ingest.json()["accepted"] == 2

    detail = await client.get("/api/v1/sessions/sess-happy-02")
    assert detail.status_code == 200, detail.text
    row = detail.json()
    assert row["tools_count"] == 1
    assert row["files_count"] == 1
    assert row["files_changed"] == ["src/foo.py"]
    assert row["user"] == user
