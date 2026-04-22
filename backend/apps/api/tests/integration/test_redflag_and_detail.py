"""Wave-12 E3 — red-flag propagation + session detail integration tests.

Covers:
  - case #3: file_change to `.env.production` flips session.flagged=True
             and unions `env_mutation` into session.flags (BACKEND-API-V0.md
             §4.1 + §5 / red_flags.py `_ENV_MUTATION_RE`).
  - case #5: 5 events posted out-of-order in one batch are returned ts ASC
             on the detail endpoint and aggregates count Write+Edit as
             file_change, Bash+Read as tool_use (§4.3).

Notes on brief drift (documented inline, no silent pivot):
  * Brief shows `?user=<authed_user>&flagged=true` for the list call — the
    sessions router has NO `user` query param; FastAPI silently drops it
    and the response is already bearer-scoped to current_user. Equivalent
    behavior, less noise — passing only `flagged=true`.
  * Brief case #5 omits `path` on Write/Edit events but asserts
    `files_count == 2`. The router increments files_count only when
    `kind == file_change AND e.path is set` (events_router.py:139). Adding
    distinct paths to Write+Edit preserves the brief's intent (2 file
    changes, 3 tool calls) without modifying the router.
"""
from __future__ import annotations

import datetime as dt

import pytest

# Force SQLModel metadata registration so the autouse `clean_db` fixture in
# conftest.py can resolve receipt tables when this module is run in isolation.
from apps.api.api.routers.receipt import models  # noqa: F401


@pytest.mark.integration
async def test_env_file_change_flags_session(authed_client):
    client, user, _token = authed_client
    session_id = "sess-flag-01"

    ingest = await client.post(
        "/api/v1/sessions/events",
        json={
            "events": [
                {
                    "session_id": session_id,
                    "tool_name": "Bash",
                    "content": "ls",
                },
                {
                    "session_id": session_id,
                    "tool_name": "Edit",
                    "path": ".env.production",
                    "content": "STRIPE_KEY=...secret...",
                },
            ]
        },
    )
    assert ingest.status_code == 202, ingest.text
    body = ingest.json()
    assert session_id in body["flagged_sessions"], body

    listing = await client.get(
        "/api/v1/sessions",
        params={"flagged": "true"},
    )
    assert listing.status_code == 200, listing.text
    listed = listing.json()
    assert listed["total"] >= 1, listed
    items = listed["items"]
    # clean_db truncates so this user only owns sess-flag-01 in this run.
    flagged_item = next(s for s in items if s["id"] == session_id)
    assert flagged_item["flagged"] is True
    assert flagged_item["user"] == user
    assert "env_mutation" in flagged_item["flags"], flagged_item

    # Optional secret_stripe assertion intentionally skipped: the brief's
    # placeholder content "STRIPE_KEY=...secret..." does NOT match
    # red_flags._SECRET_PATTERNS["secret_stripe"]
    # (`sk_(?:live|test)_[0-9a-zA-Z]{24,}`). Asserting it would require
    # injecting a real-shape token, which the brief explicitly leaves as
    # "skip if flaky" — kept skipped to honor the §5 rule definitions.


@pytest.mark.integration
async def test_session_detail_events_chronological(authed_client):
    client, _user, _token = authed_client
    session_id = "sess-det-01"

    now = dt.datetime.now(dt.timezone.utc)
    # Order in the batch is intentionally NOT chronological so we can
    # verify the server orders by ts on read (BACKEND-API-V0.md §4.3).
    # Tools chosen to land 3 in tool_use (Bash, Read, Bash) and 2 in
    # file_change (Write, Edit) per events_router._FILE_CHANGE_TOOLS.
    plan = [
        (4, "Bash", None),
        (2, "Read", None),
        (0, "Write", "src/a.py"),
        (1, "Edit", "src/b.py"),
        (3, "Bash", None),
    ]
    events = []
    for minutes_ago, tool, path in plan:
        ev = {
            "session_id": session_id,
            "ts": (now - dt.timedelta(minutes=minutes_ago)).isoformat(),
            "tool_name": tool,
            "content": "x",
        }
        if path is not None:
            ev["path"] = path
        events.append(ev)

    ingest = await client.post(
        "/api/v1/sessions/events",
        json={"events": events},
    )
    assert ingest.status_code == 202, ingest.text

    detail = await client.get(f"/api/v1/sessions/{session_id}")
    assert detail.status_code == 200, detail.text
    row = detail.json()

    assert len(row["events"]) == 5, row["events"]

    # Parse server-returned timestamps (server stores naive UTC per
    # self-learning §"SQLite drops tzinfo — normalize at the router
    # boundary"; we compare relative ordering on the parsed values).
    parsed = [dt.datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
              for e in row["events"]]
    for earlier, later in zip(parsed, parsed[1:]):
        assert earlier <= later, (parsed, row["events"])

    assert row["tools_count"] == 3, row
    assert row["files_count"] == 2, row
    # files_changed shape is now [{path, op, additions, deletions}] (v1 enrichment).
    assert sorted(f["path"] for f in row["files_changed"]) == ["src/a.py", "src/b.py"], row
