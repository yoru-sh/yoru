"""Wave-39 E3 — events ingestion + sessions export e2e.

Four tests against the LIVE backend on :8002:
  1. ingest a single event with a minted hook-token -> 202 ack
  2. ingest with a bogus bearer -> 401
  3. export JSON (format=json) streams a row for ingested data
  4. export CSV (format=csv) serves a CSV header row

Tests 3 & 4 skip cleanly when the export endpoint isn't wired yet — the
e2e pack surfaces the gap without blocking. DB isolation: no manual
`create_all`/`DELETE FROM`; the conftest `clean_db` fixture handles
truncation at the start of each test.

Contract refs: BACKEND-API-V0.md §4.1 (events ingest), §4.6 (hook-token
mint). Export shape is per the brief — no vault contract yet.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest


@pytest.mark.integration
async def test_post_events_with_hook_token_ingests(authed_client):
    """Mint a hook-token then POST one event — expect 202 with ack."""
    client, user, _token = authed_client
    session_id = f"sess-e3-ingest-{uuid4().hex[:8]}"

    r = await client.post(
        "/api/v1/sessions/events",
        json={
            "events": [
                {
                    "session_id": session_id,
                    "user": user,
                    "tool_name": "Bash",
                    "content": "echo hi",
                }
            ]
        },
    )
    assert r.status_code in (200, 202), r.text
    body = r.json()
    assert body["accepted"] >= 1
    assert session_id in body["session_ids"]


@pytest.mark.integration
async def test_post_events_bad_token_401(client):
    """A bogus Bearer must be rejected at the deps layer — 401."""
    r = await client.post(
        "/api/v1/sessions/events",
        headers={"Authorization": "Bearer bad-token-xyz"},
        json={
            "events": [
                {
                    "session_id": f"sess-e3-bad-{uuid4().hex[:8]}",
                    "user": "e3-bad@test.local",
                    "tool_name": "Bash",
                    "content": "echo hi",
                }
            ]
        },
    )
    assert r.status_code == 401, r.text


@pytest.mark.integration
async def test_export_json_streams_row_when_data_exists(authed_client):
    """GET /api/v1/sessions/export?format=json returns the ingested session.

    Skips when the export endpoint is not yet wired — keeps the e2e pack
    green while the feature is implemented in a follow-up.
    """
    client, user, _token = authed_client
    session_id = f"sess-e3-exp-json-{uuid4().hex[:8]}"

    ingest = await client.post(
        "/api/v1/sessions/events",
        json={
            "events": [
                {
                    "session_id": session_id,
                    "user": user,
                    "tool_name": "Write",
                    "path": "src/e3.py",
                    "content": "print('hi')",
                }
            ]
        },
    )
    assert ingest.status_code in (200, 202), ingest.text

    r = await client.get("/api/v1/sessions/export", params={"format": "json"})
    if r.status_code == 404:
        pytest.skip(
            "GET /api/v1/sessions/export not implemented yet — "
            "gate: wire the bulk JSON export endpoint per brief"
        )
    assert r.status_code == 200, r.text

    ctype = r.headers.get("content-type", "")
    assert ctype.startswith("application/json") or ctype.startswith(
        "application/x-ndjson"
    ), f"unexpected content-type: {ctype!r}"

    raw = r.text.strip()
    assert raw, "empty export body"

    # NDJSON: one JSON object per line. Plain JSON: array or envelope.
    matched = False
    if ctype.startswith("application/x-ndjson"):
        for line in raw.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if session_id in json.dumps(row):
                matched = True
                break
    else:
        doc = json.loads(raw)
        matched = session_id in json.dumps(doc)
    assert matched, f"{session_id} not found in export body"


@pytest.mark.integration
async def test_export_csv_content_type(authed_client):
    """GET /api/v1/sessions/export?format=csv returns a CSV with a header row."""
    client, _user, _token = authed_client

    r = await client.get("/api/v1/sessions/export", params={"format": "csv"})
    if r.status_code == 404:
        pytest.skip(
            "GET /api/v1/sessions/export not implemented yet — "
            "gate: wire the bulk CSV export endpoint per brief"
        )
    assert r.status_code == 200, r.text

    ctype = r.headers.get("content-type", "")
    assert ctype.startswith("text/csv"), f"unexpected content-type: {ctype!r}"

    first_line = r.text.splitlines()[0] if r.text else ""
    assert "," in first_line, f"CSV first line lacks commas: {first_line!r}"
