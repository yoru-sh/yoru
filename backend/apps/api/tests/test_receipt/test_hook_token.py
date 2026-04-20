"""Integration tests — hook-token endpoints (§4.6–§4.8).

Six atomic cases per CTO brief; end-to-end via TestClient, no router edits.
Contract: vault/BACKEND-API-V0.md §4.6–§4.8, vault/AUTH-V0.md §1(a).
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _mint(client: TestClient, user: str, label: str | None = None) -> dict:
    payload: dict = {"user": user}
    if label is not None:
        payload["label"] = label
    resp = client.post("/api/v1/auth/hook-token", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# 1. Mint happy path — §4.6
def test_mint_happy_path(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/hook-token",
        json={"user": "alice@example.com", "label": "laptop"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token"].startswith("rcpt_")
    assert body["user"] == "alice@example.com"


# 2. List requires auth — §4.7
def test_list_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/hook-tokens")
    assert resp.status_code == 401


# 3. List scoped to caller — §4.7 (cross-user isolation)
def test_list_scoped_to_caller(client: TestClient) -> None:
    a1 = _mint(client, "alice@example.com", "laptop")
    _mint(client, "alice@example.com", "desktop")
    bob = _mint(client, "bob@example.com", "laptop")

    resp = client.get(
        "/api/v1/auth/hook-tokens",
        headers={"Authorization": f"Bearer {a1['token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    ids = {row["id"] for row in body}
    assert bob["user_id"] not in ids


# 4. Revoke happy (idempotent) — §4.8
def test_revoke_happy_is_idempotent(client: TestClient) -> None:
    auth = _mint(client, "alice@example.com", "auth")  # bearer, kept live
    target = _mint(client, "alice@example.com", "to-revoke")
    headers = {"Authorization": f"Bearer {auth['token']}"}

    r1 = client.delete(f"/api/v1/auth/hook-token/{target['user_id']}", headers=headers)
    assert r1.status_code == 204, r1.text

    r2 = client.delete(f"/api/v1/auth/hook-token/{target['user_id']}", headers=headers)
    assert r2.status_code == 204, r2.text


# 5. Revoke cross-user → 401 — §4.8 acceptance + AUTH-V0 §1(a)
def test_revoke_cross_user_returns_401(client: TestClient) -> None:
    alice = _mint(client, "alice@example.com", "laptop")
    bob = _mint(client, "bob@example.com", "laptop")

    resp = client.delete(
        f"/api/v1/auth/hook-token/{bob['user_id']}",
        headers={"Authorization": f"Bearer {alice['token']}"},
    )
    assert resp.status_code == 401


# 6. Revoke unknown id → 404 — §4.8
def test_revoke_unknown_returns_404(client: TestClient) -> None:
    alice = _mint(client, "alice@example.com", "laptop")
    resp = client.delete(
        "/api/v1/auth/hook-token/00000000000000000000000000000000",
        headers={"Authorization": f"Bearer {alice['token']}"},
    )
    assert resp.status_code == 404
