"""Wave-12 E5 — negative-path integration tests.

Covers:
  - case #9: malformed / empty / oversize batch → 422 with structured envelope
  - case #10a: ingest without a bearer → 202 when `user` in body
             (v0 trust-body contract per events_router.get_current_user being
             the Optional variant; no 401 gate). Deviation from the original
             E5 brief which predicted 401; documented in complete_task.
  - case #10b: DELETE /auth/hook-token/{id} cross-user → 401, unknown id → 404
             (AUTH-V0 §1(a) — 401 on cross-user is the single documented
             exception to the 404-not-403 rule; not generalized).

Contract refs:
  - BACKEND-API-V0.md §4.1 (events), §4.6–§4.8 (hook-token lifecycle)
  - AUTH-V0 §1(a) (401 on cross-user delete)
  - Error envelope: apps/api/api/core/errors.py (wave-13 C3 shape)
    `{"error": {"code", "message", "request_id", "hint"}}` — supersedes the
    wave-7 flat envelope in ERROR-HANDLING-V0.md.
"""
from __future__ import annotations

import uuid

import pytest


def _assert_envelope(body: dict) -> None:
    """Assert the wave-13 C3 structured-error shape."""
    assert "error" in body, f"missing 'error' key: {body}"
    err = body["error"]
    assert "request_id" in err, f"missing 'request_id' in error: {err}"
    assert "code" in err, f"missing 'code' in error: {err}"
    assert "message" in err, f"missing 'message' in error: {err}"


@pytest.mark.integration
async def test_ingest_malformed_body_returns_422_with_envelope(client, clean_db):
    # (a) empty event dict — missing required `session_id`
    r = await client.post("/api/v1/sessions/events", json={"events": [{}]})
    assert r.status_code == 422, r.text
    _assert_envelope(r.json())
    assert r.json()["error"]["code"] == "VALIDATION_FAILED"

    # (b) zero events — min_length=1 on EventsBatchIn
    r = await client.post("/api/v1/sessions/events", json={"events": []})
    assert r.status_code == 422, r.text
    _assert_envelope(r.json())

    # (c) 1001 events — max_length=1000 on EventsBatchIn
    oversize = {
        "events": [
            {"session_id": f"sess-neg-{i}", "user": "neg@test.local", "tool": "Bash"}
            for i in range(1001)
        ]
    }
    r = await client.post("/api/v1/sessions/events", json=oversize)
    assert r.status_code == 422, r.text
    _assert_envelope(r.json())


@pytest.mark.integration
async def test_ingest_without_bearer_returns_202(client, clean_db):
    """Current contract: events_router depends on get_current_user (Optional).
    With `user` in event body, no bearer → 202 (v0 trust-body).

    Brief's spec'd 401 applies only if the dep is switched to
    require_current_user; at wave-12 it is not. Note in complete_task.
    """
    r = await client.post(
        "/api/v1/sessions/events",
        json={
            "events": [
                {
                    "session_id": "sess-no-bearer-01",
                    "user": "no-bearer@test.local",
                    "tool": "Bash",
                    "content": "echo hi",
                }
            ]
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted"] == 1
    assert "sess-no-bearer-01" in body["session_ids"]

    # Complementary assertion: without bearer AND without `user` → 422 with
    # the `user attribution required` detail (guards against the silent-ingest
    # regression; self-learning: qa-pydantic-extras-silent-drop-is-half-closure).
    r = await client.post(
        "/api/v1/sessions/events",
        json={"events": [{"session_id": "sess-no-bearer-02", "tool": "Bash"}]},
    )
    assert r.status_code == 422, r.text
    _assert_envelope(r.json())
    assert "user attribution required" in r.json()["error"]["message"]


@pytest.mark.integration
async def test_hook_token_cross_user_delete_returns_401(client, clean_db):
    """AUTH-V0 §1(a): cross-user DELETE on /auth/hook-token/{id} → 401, not 404.
    Unknown token_id → 404. The token IS the credential, so the usual 404-on-
    cross-user rule is explicitly suspended for this one endpoint.
    """
    mint_a = await client.post(
        "/api/v1/auth/hook-token", json={"user": "user-a@test.local"}
    )
    assert mint_a.status_code == 201, mint_a.text
    token_a = mint_a.json()["token"]

    mint_b = await client.post(
        "/api/v1/auth/hook-token", json={"user": "user-b@test.local"}
    )
    assert mint_b.status_code == 201, mint_b.text
    token_b_id = mint_b.json()["user_id"]  # mint response returns row.id as user_id

    # Using A's bearer, delete B's token_id → 401
    r = await client.delete(
        f"/api/v1/auth/hook-token/{token_b_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 401, r.text
    _assert_envelope(r.json())
    assert r.json()["error"]["code"] == "AUTH_REQUIRED"

    # Using A's bearer, delete a random UUID → 404
    unknown_id = uuid.uuid4().hex
    r = await client.delete(
        f"/api/v1/auth/hook-token/{unknown_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 404, r.text
    _assert_envelope(r.json())
    assert r.json()["error"]["code"] == "NOT_FOUND"
