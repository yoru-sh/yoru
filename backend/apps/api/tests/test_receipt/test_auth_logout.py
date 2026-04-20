"""Tests for POST /api/v1/auth/logout (wave-14 C3).

Contract: logout revokes the bearer (stamps `revoked_at`), returns 204.
Missing / unknown / already-revoked bearer → 401 with the typed error
envelope (ERROR-HANDLING-V0 shape: {"error": {code, message, request_id, hint}}).
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from apps.api.api.core.errors import install_error_handlers
from apps.api.api.routers.receipt.auth_router import AuthRouter
from apps.api.api.routers.receipt.db import get_session
from apps.api.api.routers.receipt.models import HookToken
from apps.api.core.request_logging import RequestLoggingMiddleware


@pytest.fixture()
def app(engine) -> FastAPI:
    """Shadow the conftest app to add envelope handlers + request-id middleware.

    Without these, 401 responses would skip the typed envelope and the
    `typed envelope` acceptance criterion couldn't be verified.
    """
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    install_error_handlers(app)
    app.include_router(AuthRouter().get_router(), prefix="/api/v1")

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    return app


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


def _assert_envelope(body: dict, expected_code: str) -> None:
    assert set(body.keys()) == {"error"}, body
    err = body["error"]
    assert {"code", "message", "request_id"}.issubset(err.keys()), err
    assert err["code"] == expected_code
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["request_id"], str) and err["request_id"]


def test_logout_happy_204(client: TestClient, engine) -> None:
    # Mint a fresh token.
    mint = client.post("/api/v1/auth/hook-token", json={"user": "alice"})
    assert mint.status_code == 201, mint.text
    raw = mint.json()["token"]
    headers = {"Authorization": f"Bearer {raw}"}

    # First logout → 204 and row.revoked_at populated.
    r1 = client.post("/api/v1/auth/logout", headers=headers)
    assert r1.status_code == 204, r1.text
    assert r1.content == b""

    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    with Session(engine) as s:
        row = s.exec(
            select(HookToken).where(HookToken.token_hash == token_hash)
        ).one()
    assert row.revoked_at is not None

    # Second logout with the same bearer → 401 (replay-prevention).
    r2 = client.post("/api/v1/auth/logout", headers=headers)
    assert r2.status_code == 401, r2.text
    _assert_envelope(r2.json(), "AUTH_REQUIRED")


def test_logout_no_bearer_401(client: TestClient) -> None:
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 401
    _assert_envelope(r.json(), "AUTH_REQUIRED")
    assert "X-Request-ID" in r.headers


def test_logout_unknown_bearer_401(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": "Bearer rcpt_notreal"},
    )
    assert r.status_code == 401
    _assert_envelope(r.json(), "AUTH_REQUIRED")
