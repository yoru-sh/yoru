"""Wave-53 C1b — e2e ingest→detail→trail roundtrip + token-surfacing harness.

Regression harness that proves a single ingest batch surfaces consistent data
across `GET /sessions/{id}` (detail) and `GET /sessions/{id}/trail` (compliance
export), with token counts aggregated correctly and the trail's
`Content-Disposition` header wired for `curl -OJ`.

Contract refs:
  - BACKEND-API-V0.md §4.1 (events ingest + aggregate update rules)
  - BACKEND-API-V0.md §4.3 (session detail shape)
  - BACKEND-API-V0.md §4.9 (trail export + attachment header + schema_version)
  - INTEGRATION-TESTS-V0.md (no mocks; live :8002, clean_db autouse)

Parent task: cdb7cc69 (wave-53 ingest-trail-export C1 split). Export leg
(`/sessions/export`) is deferred to C1c — explicitly NOT asserted here.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest


@pytest.mark.integration
async def test_ingest_trail_roundtrip_surfaces_tokens_and_attachment_header(
    authed_client,
):
    """One batch of 3 mixed-kind events → detail aggregates + trail shape + tokens.

    Asserts (≥4 per brief):
      1. Detail: status 200 + len(events) == 3 + aggregate tokens_input /
         tokens_output / cost_usd equal the POSTed sum.
      2. Trail: status 200 + schema_version == "v0" + len(events) == 3.
      3. Trail header: `Content-Disposition: attachment; filename="receipt-{id}.json"`.
      4. Trail `exported_at` parses as a UTC-aware ISO-8601 timestamp.
      5. Token consistency: per-event tokens in trail match the POSTed values
         AND the session-level aggregate equals the per-event sum.
    """
    client, _user, _token = authed_client
    # Unique per run — integration DB lives at backend/data/receipt.db (not
    # truncated between runs in a worktree context), so a stable id would
    # collide with a prior-run session owned by a different bearer user and
    # trip the §4.3 cross-user 404 guard.
    session_id = f"sess-c1b-{uuid4().hex[:10]}"

    posted = [
        {
            "session_id": session_id,
            "kind": "tool_use",
            "tool": "Bash",
            "content": "echo hello",
            "tokens_input": 120,
            "tokens_output": 40,
            "cost_usd": 0.0012,
        },
        {
            "session_id": session_id,
            "kind": "file_change",
            "path": "src/app.py",
            "content": "pass",
            "tokens_input": 30,
            "tokens_output": 10,
            "cost_usd": 0.0003,
        },
        {
            "session_id": session_id,
            "kind": "token",
            "content": "claude turn accounting",
            "tokens_input": 500,
            "tokens_output": 250,
            "cost_usd": 0.0085,
        },
    ]
    expected_tokens_input = sum(e["tokens_input"] for e in posted)
    expected_tokens_output = sum(e["tokens_output"] for e in posted)
    expected_cost = sum(e["cost_usd"] for e in posted)

    ingest = await client.post(
        "/api/v1/sessions/events", json={"events": posted}
    )
    assert ingest.status_code == 202, ingest.text
    assert ingest.json()["accepted"] == 3

    # ---------- Detail shape + aggregates ----------
    detail_resp = await client.get(f"/api/v1/sessions/{session_id}")
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert len(detail["events"]) == 3, detail["events"]
    assert detail["tokens_input"] == expected_tokens_input, detail
    assert detail["tokens_output"] == expected_tokens_output, detail
    assert detail["cost_usd"] == pytest.approx(expected_cost), detail

    # ---------- Trail shape + attachment header ----------
    trail_resp = await client.get(f"/api/v1/sessions/{session_id}/trail")
    assert trail_resp.status_code == 200, trail_resp.text

    cd = trail_resp.headers.get("content-disposition", "")
    assert cd == f'attachment; filename="receipt-{session_id}.json"', cd

    trail = trail_resp.json()
    assert trail["schema_version"] == "v0", trail["schema_version"]
    assert len(trail["events"]) == 3, trail["events"]

    exported = datetime.fromisoformat(trail["exported_at"])
    assert exported.tzinfo is not None and exported.utcoffset().total_seconds() == 0, (
        f"exported_at must be UTC-aware ISO-8601; got {trail['exported_at']!r}"
    )

    # ---------- Token consistency (per-event + session-level) ----------
    posted_by_kind = {e["kind"]: e for e in posted}
    for ev in trail["events"]:
        src = posted_by_kind[ev["kind"]]
        assert ev["tokens_input"] == src["tokens_input"], (ev, src)
        assert ev["tokens_output"] == src["tokens_output"], (ev, src)

    assert trail["session"]["tokens_input"] == expected_tokens_input
    assert trail["session"]["tokens_output"] == expected_tokens_output
    assert sum(e["tokens_input"] for e in trail["events"]) == expected_tokens_input
    assert sum(e["tokens_output"] for e in trail["events"]) == expected_tokens_output
