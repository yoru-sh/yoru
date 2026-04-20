"""Tests for the hook-token auth router (mint / list / revoke).

Contract: BACKEND-API-V0.md §4.6–§4.8, AUTH-V0.md §1(a).
"""
from __future__ import annotations

import hashlib
import re

from fastapi.testclient import TestClient
from sqlmodel import Session as DBSession, select

from apps.api.api.routers.receipt.models import HookToken


_UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


# ---------- mint ----------

def test_mint_happy_path(client: TestClient, engine) -> None:
    resp = client.post("/api/v1/auth/hook-token", json={"user": "alice"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"] == "alice"
    assert body["token"].startswith("rcpt_")
    assert len(body["token"]) > len("rcpt_") + 16
    assert _UUID_HEX.match(body["user_id"])

    # sha256 of the returned raw token must match the persisted hash.
    expected_hash = hashlib.sha256(body["token"].encode("utf-8")).hexdigest()
    with DBSession(engine) as s:
        rows = s.exec(select(HookToken).where(HookToken.user == "alice")).all()
    assert len(rows) == 1
    assert rows[0].token_hash == expected_hash
    assert rows[0].id == body["user_id"]
    assert rows[0].revoked_at is None
    assert rows[0].last_used_at is None


def test_mint_with_label(client: TestClient, engine) -> None:
    resp = client.post(
        "/api/v1/auth/hook-token",
        json={"user": "bob", "label": "laptop-01"},
    )
    assert resp.status_code == 201
    with DBSession(engine) as s:
        row = s.exec(select(HookToken).where(HookToken.user == "bob")).one()
    assert row.label == "laptop-01"


def test_mint_rejects_empty_user(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/hook-token", json={"user": ""})
    assert resp.status_code == 422


def test_mint_rejects_missing_user(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/hook-token", json={})
    assert resp.status_code == 422


# ---------- list ----------

def test_list_requires_bearer(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/hook-tokens")
    assert resp.status_code == 401


def test_list_empty_returns_empty_array(client: TestClient, mint_token) -> None:
    # alice has a token just to authenticate; list should only include it.
    _, headers = mint_token("alice")
    resp = client.get("/api/v1/auth/hook-tokens", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["label"] is None
    assert body[0]["revoked_at"] is None
    assert "created_at" in body[0]


def test_list_scopes_to_caller(client: TestClient, mint_token) -> None:
    _, alice_headers = mint_token("alice")
    mint_token("alice")  # second alice token
    mint_token("bob")     # bob's token — must not leak
    resp = client.get("/api/v1/auth/hook-tokens", headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2  # alice's two tokens, never bob's


def test_list_surfaces_revoked_row(client: TestClient, mint_token) -> None:
    _, headers = mint_token("alice")
    mint_token("alice", revoked=True)
    resp = client.get("/api/v1/auth/hook-tokens", headers=headers)
    body = resp.json()
    assert len(body) == 2
    revoked_rows = [r for r in body if r["revoked_at"] is not None]
    assert len(revoked_rows) == 1


# ---------- revoke ----------

def test_revoke_happy_path(client: TestClient, engine, mint_token) -> None:
    _, headers = mint_token("alice")
    # a second token we will revoke
    mint_token("alice")
    list_before = client.get("/api/v1/auth/hook-tokens", headers=headers).json()
    target = next(r["id"] for r in list_before if r["revoked_at"] is None)
    # but pick the one that's NOT the auth token — we'll revoke the second.
    target_ids = [r["id"] for r in list_before]
    assert len(target_ids) == 2
    # pick first (either works; we just don't want the *request* token)
    # Easiest: revoke the non-auth one. The auth token's id is unknown without
    # mint_token returning it, so revoke any and confirm revoked_at populated.
    revoke_id = target_ids[0]

    resp = client.delete(
        f"/api/v1/auth/hook-token/{revoke_id}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    with DBSession(engine) as s:
        row = s.get(HookToken, revoke_id)
    assert row is not None
    assert row.revoked_at is not None


def test_revoke_is_idempotent(client: TestClient, mint_token) -> None:
    _, headers = mint_token("alice")
    list_rows = client.get("/api/v1/auth/hook-tokens", headers=headers).json()
    target_id = list_rows[0]["id"]
    r1 = client.delete(f"/api/v1/auth/hook-token/{target_id}", headers=headers)
    assert r1.status_code == 204
    # After revoking the only token, the caller's bearer is revoked too —
    # further DELETE attempts will 401. Spin up a fresh token for the next call.
    _, fresh_headers = mint_token("alice")
    r2 = client.delete(
        f"/api/v1/auth/hook-token/{target_id}",
        headers=fresh_headers,
    )
    assert r2.status_code == 204


def test_revoke_unknown_returns_404(client: TestClient, mint_token) -> None:
    _, headers = mint_token("alice")
    resp = client.delete(
        "/api/v1/auth/hook-token/deadbeef-does-not-exist",
        headers=headers,
    )
    assert resp.status_code == 404


def test_revoke_cross_user_returns_401(client: TestClient, mint_token) -> None:
    _, alice_headers = mint_token("alice")
    # Bob mints a token we want to steal.
    bob_list = []
    mint_token("bob")
    # Look up bob's token id via bob's own auth.
    _, bob_headers = mint_token("bob")
    bob_list = client.get("/api/v1/auth/hook-tokens", headers=bob_headers).json()
    bob_token_id = bob_list[0]["id"]

    resp = client.delete(
        f"/api/v1/auth/hook-token/{bob_token_id}",
        headers=alice_headers,
    )
    assert resp.status_code == 401


def test_revoke_requires_bearer(client: TestClient, mint_token) -> None:
    _, headers = mint_token("alice")
    token_id = client.get("/api/v1/auth/hook-tokens", headers=headers).json()[0]["id"]
    # No auth header
    resp = client.delete(f"/api/v1/auth/hook-token/{token_id}")
    assert resp.status_code == 401


# ---------- last_used_at write-through ----------

def test_last_used_at_populated_after_auth_call(
    client: TestClient, engine, mint_token
) -> None:
    raw, headers = mint_token("alice")
    # Before any authenticated request, last_used_at should be None.
    with DBSession(engine) as s:
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        row_before = s.exec(
            select(HookToken).where(HookToken.token_hash == token_hash)
        ).one()
    assert row_before.last_used_at is None

    # Any bearer-required call triggers _resolve_token → write-through.
    resp = client.get("/api/v1/auth/hook-tokens", headers=headers)
    assert resp.status_code == 200

    with DBSession(engine) as s:
        row_after = s.exec(
            select(HookToken).where(HookToken.token_hash == token_hash)
        ).one()
    assert row_after.last_used_at is not None
    # naive UTC per deps._naive_utc_now
    assert row_after.last_used_at.tzinfo is None


def test_revoked_token_returns_401(client: TestClient, mint_token) -> None:
    # Revoke-then-reuse must 401 on any bearer-required route.
    raw, headers = mint_token("alice", revoked=True)
    resp = client.get("/api/v1/auth/hook-tokens", headers=headers)
    assert resp.status_code == 401
