"""E2E v1 — sessions CRUD against live backend on :8002.

Wave-39 E2 (`8a2985b0`). Hits a real uvicorn — NO mocks. Auth is hook-token
(POST /api/v1/auth/hook-token); there is no signup/login pair on the backend.
Sessions are created implicitly by the events ingestion router (POST
/api/v1/sessions/events) — no standalone POST /api/v1/sessions exists. Brief
contemplates this divergence: "the brief is the intent; the router is the
source of truth."

Local fixtures (`backend_base_url`, `backend_up`) are intentionally defined
in-file rather than reused from `conftest.py` — the existing conftest fixtures
are differently shaped (`client`, `authed_client`) and "DO NOT touch existing
pytest files" applies. Per loic's DB-WIPE rule: this file performs NO
`create_all` / `DELETE FROM`; unique uuid suffixes per run isolate test rows.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest


@pytest.fixture
def backend_base_url() -> str:
    return os.environ.get("RECEIPT_INTEGRATION_URL", "http://localhost:8002")


@pytest.fixture
def backend_up(backend_base_url: str) -> str:
    try:
        r = httpx.get(f"{backend_base_url}/health", timeout=2.0)
    except httpx.TransportError:
        pytest.skip(f"backend not up on {backend_base_url}")
    if r.status_code != 200:
        pytest.skip(f"backend not healthy: /health -> {r.status_code}")
    return backend_base_url


def _mint_hook_token(base_url: str) -> tuple[str, str]:
    user = f"e2e-sessions-{uuid.uuid4().hex[:8]}@test.local"
    r = httpx.post(
        f"{base_url}/api/v1/auth/hook-token",
        json={"user": user, "label": "e2e-sessions"},
        timeout=5.0,
    )
    assert r.status_code == 201, f"hook-token mint failed: {r.status_code} {r.text}"
    return user, r.json()["token"]


@pytest.mark.integration
def test_authed_create_session_returns_id(backend_up: str) -> None:
    """POST /api/v1/sessions/events with a valid bearer creates a session row.

    No standalone POST /api/v1/sessions exists; sessions are created on first
    event for an unseen session_id. The 202 response carries `session_ids`
    listing the created/touched sessions — that's the "id" the brief expects.
    """
    base_url = backend_up
    _, token = _mint_hook_token(base_url)
    session_id = f"e2e-sess-{uuid.uuid4().hex[:12]}"

    payload = {
        "events": [
            {
                "session_id": session_id,
                "tool": "Bash",
                "kind": "tool_use",
                "content": "echo wave-39-E2",
            }
        ]
    }
    r = httpx.post(
        f"{base_url}/api/v1/sessions/events",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    assert r.status_code == 202, f"unexpected status: {r.status_code} {r.text}"
    body = r.json()
    assert body["accepted"] >= 1
    assert session_id in body["session_ids"]


@pytest.mark.integration
def test_get_session_by_id_round_trip(backend_up: str) -> None:
    """Create a session via events ingest, then GET /api/v1/sessions/{id} returns it."""
    base_url = backend_up
    _, token = _mint_hook_token(base_url)
    session_id = f"e2e-sess-{uuid.uuid4().hex[:12]}"
    headers = {"Authorization": f"Bearer {token}"}

    ingest = httpx.post(
        f"{base_url}/api/v1/sessions/events",
        json={
            "events": [
                {
                    "session_id": session_id,
                    "tool": "Read",
                    "kind": "tool_use",
                    "path": "/tmp/wave-39-e2.txt",
                }
            ]
        },
        headers=headers,
        timeout=10.0,
    )
    assert ingest.status_code == 202, ingest.text

    r = httpx.get(
        f"{base_url}/api/v1/sessions/{session_id}",
        headers=headers,
        timeout=10.0,
    )
    assert r.status_code == 200, f"GET failed: {r.status_code} {r.text}"
    body = r.json()
    assert body["id"] == session_id
    # SessionDetail shape per BACKEND-API-V0.md §4.3
    for key in ("started_at", "tools_count", "files_count", "cost_usd", "events"):
        assert key in body, f"missing {key} in SessionDetail response: {body!r}"
    assert isinstance(body["events"], list) and len(body["events"]) >= 1


@pytest.mark.integration
def test_unauthed_get_sessions_401(backend_up: str) -> None:
    """GET /api/v1/sessions/{id} without an Authorization header → 401.

    `require_current_user` raises 401 when no bearer is present, regardless of
    whether the session exists (auth check runs first).
    """
    base_url = backend_up
    session_id = f"nonexistent-{uuid.uuid4().hex[:12]}"
    r = httpx.get(f"{base_url}/api/v1/sessions/{session_id}", timeout=5.0)
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"
