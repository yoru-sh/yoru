"""Tests for the Receipt v0 summary stub router (BACKEND-API-V0 §4.4/§4.5).

Auth enforcement per AUTH-V0 §1(c): summary POST/GET require a bearer hook-token,
cross-user access returns 404 (not 403) to avoid leaking existence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from sqlmodel import Session as SQLSession

from apps.api.api.routers.receipt.models import Session as SessionRow


@pytest.fixture()
def app(engine) -> FastAPI:
    """Override conftest.app to mount only SummaryRouter.

    Isolates this module from a sibling's in-progress AuthRouter (backend-lead's
    revoke endpoint) which ImportErrors until its 204+body assertion lands fixed.
    Pattern per self-learning §"parallel-dev-conftest-override".
    """
    from apps.api.api.routers.receipt.db import get_session
    from apps.api.api.routers.receipt.summary_router import SummaryRouter

    _app = FastAPI()
    _app.include_router(SummaryRouter().get_router(), prefix="/api/v1")

    def _override():
        with SQLSession(engine) as s:
            yield s

    _app.dependency_overrides[get_session] = _override
    return _app


def _naive(d: datetime) -> datetime:
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


@pytest.fixture()
def alice_headers(mint_token):
    _, h = mint_token("alice")
    return h


def _seed(db_session, **overrides: Any) -> SessionRow:
    defaults: dict[str, Any] = {
        "id": "sess-1",
        "user": "alice",
        "started_at": _naive(datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc)),
        "ended_at": _naive(datetime(2026, 4, 20, 10, 2, 30, tzinfo=timezone.utc)),
        "tools_count": 4,
        "files_count": 2,
        "tokens_input": 1000,
        "tokens_output": 250,
        "cost_usd": 0.0375,
        "flags": [],
    }
    defaults.update(overrides)
    row = SessionRow(**defaults)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_post_generates_and_persists(client, db_session, alice_headers):
    _seed(
        db_session,
        id="s-gen",
        tools_count=3,
        files_count=2,
        tokens_input=100,
        tokens_output=50,
        cost_usd=1.5,
        flags=[],
    )
    r = client.post("/api/v1/sessions/s-gen/summary", headers=alice_headers)
    assert r.status_code == 200

    body = r.json()
    assert body["session_id"] == "s-gen"
    assert "generated_at" in body

    summary: str = body["summary"]
    lines = summary.split("\n")
    assert len(lines) == 3
    assert lines[0] == "3 tools across 2 files in 150s."
    assert lines[1] == "Tokens: 100\u219250  Cost: $1.50."
    assert lines[2] == "Flags: none."

    # GET after POST returns the persisted string.
    r2 = client.get("/api/v1/sessions/s-gen/summary", headers=alice_headers)
    assert r2.status_code == 200
    assert r2.json()["summary"] == summary


def test_post_overwrites_on_resubmit(client, db_session, alice_headers):
    _seed(
        db_session,
        id="s-ov",
        tools_count=1,
        files_count=0,
        tokens_input=10,
        tokens_output=5,
        cost_usd=0.01,
        flags=[],
    )
    r1 = client.post("/api/v1/sessions/s-ov/summary", headers=alice_headers)
    assert r1.status_code == 200
    first = r1.json()["summary"]

    # Mutate session fields, then re-POST.
    row = db_session.get(SessionRow, "s-ov")
    row.tools_count = 9
    row.files_count = 4
    row.tokens_input = 500
    row.tokens_output = 200
    row.cost_usd = 2.5
    row.flags = ["secret_aws", "shell_rm"]
    db_session.add(row)
    db_session.commit()

    r2 = client.post("/api/v1/sessions/s-ov/summary", headers=alice_headers)
    assert r2.status_code == 200
    second = r2.json()["summary"]
    assert first != second

    lines = second.split("\n")
    assert lines[0] == "9 tools across 4 files in 150s."
    assert lines[1] == "Tokens: 500\u2192200  Cost: $2.50."
    assert lines[2] == "Flags: secret_aws, shell_rm."

    # GET returns the overwritten (second) summary.
    r3 = client.get("/api/v1/sessions/s-ov/summary", headers=alice_headers)
    assert r3.status_code == 200
    assert r3.json()["summary"] == second


def test_post_404_when_session_missing(client, alice_headers):
    r = client.post("/api/v1/sessions/does-not-exist/summary", headers=alice_headers)
    assert r.status_code == 404


def test_get_404_when_session_missing(client, alice_headers):
    r = client.get("/api/v1/sessions/does-not-exist/summary", headers=alice_headers)
    assert r.status_code == 404


def test_get_404_when_summary_none(client, db_session, alice_headers):
    _seed(db_session, id="s-no-sum")
    # POST was never called; Session.summary is None.
    r = client.get("/api/v1/sessions/s-no-sum/summary", headers=alice_headers)
    assert r.status_code == 404


def test_flags_joined_with_comma_space_and_period(client, db_session, alice_headers):
    _seed(
        db_session,
        id="s-fmt",
        tools_count=7,
        files_count=3,
        tokens_input=2000,
        tokens_output=900,
        cost_usd=0.1,
        flags=["secret_aws", "shell_rm", "env_mutation"],
    )
    r = client.post("/api/v1/sessions/s-fmt/summary", headers=alice_headers)
    assert r.status_code == 200
    summary = r.json()["summary"]
    lines = summary.split("\n")

    # line 2: cost must render with a dollar sign + exactly 2 decimals.
    assert "$0.10." in lines[1]
    assert "Cost: $0.10." in lines[1]

    # line 3: flags joined with ", " and terminated by a period.
    assert lines[2] == "Flags: secret_aws, shell_rm, env_mutation."


def test_duration_zero_when_ended_at_none(client, db_session, alice_headers):
    _seed(
        db_session,
        id="s-no-end",
        ended_at=None,
        tools_count=2,
        files_count=1,
        tokens_input=0,
        tokens_output=0,
        cost_usd=0.0,
        flags=[],
    )
    r = client.post("/api/v1/sessions/s-no-end/summary", headers=alice_headers)
    assert r.status_code == 200
    lines = r.json()["summary"].split("\n")
    assert lines[0] == "2 tools across 1 files in 0s."
    assert lines[1] == "Tokens: 0\u21920  Cost: $0.00."
    assert lines[2] == "Flags: none."


def test_post_404_on_cross_user(client, db_session, alice_headers):
    """Alice POSTing summary for bob's session must get 404, not 403."""
    _seed(db_session, id="s-bob", user="bob")
    r = client.post("/api/v1/sessions/s-bob/summary", headers=alice_headers)
    assert r.status_code == 404


def test_get_404_on_cross_user(client, db_session, mint_token, alice_headers):
    """Alice reading bob's already-generated summary must get 404, not the body."""
    _seed(db_session, id="s-bob2", user="bob")
    # Bob generates their own summary first (so it's present in DB).
    _, bob_h = mint_token("bob")
    r_bob = client.post("/api/v1/sessions/s-bob2/summary", headers=bob_h)
    assert r_bob.status_code == 200
    # Alice must NOT be able to read it.
    r = client.get("/api/v1/sessions/s-bob2/summary", headers=alice_headers)
    assert r.status_code == 404


def test_post_401_without_bearer(client, db_session):
    _seed(db_session, id="s-noauth")
    r = client.post("/api/v1/sessions/s-noauth/summary")
    assert r.status_code == 401


def test_get_401_without_bearer(client, db_session):
    _seed(db_session, id="s-noauth2")
    r = client.get("/api/v1/sessions/s-noauth2/summary")
    assert r.status_code == 401
