"""Wave-13 C3 — 5-case error-envelope acceptance suite.

Every response body is `{"error": {"code", "message", "request_id", "hint"}}`
with the HTTP status code on the response. Cases cover validation,
auth-missing, cross-user 404 (AUTH-V0 §1(c)), unknown-id 404, and an
unhandled 500. Each case also verifies X-Request-ID echo/population.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from apps.api.api.core.errors import install_error_handlers
from apps.api.api.routers.receipt.auth_router import AuthRouter
from apps.api.api.routers.receipt.db import get_session
from apps.api.api.routers.receipt.events_router import EventsRouter
from apps.api.api.routers.receipt.models import Session as SessionRow
from apps.api.api.routers.receipt.sessions_router import SessionsRouter
from apps.api.api.routers.receipt.summary_router import SummaryRouter
from apps.api.core.request_logging import RequestLoggingMiddleware


@pytest.fixture()
def app(engine) -> FastAPI:
    """Shadow the conftest app to add middleware + envelope handlers."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    install_error_handlers(app)

    app.include_router(EventsRouter().get_router(), prefix="/api/v1")
    app.include_router(SessionsRouter().get_router(), prefix="/api/v1")
    app.include_router(SummaryRouter().get_router(), prefix="/api/v1")
    app.include_router(AuthRouter().get_router(), prefix="/api/v1")

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    return app


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _assert_envelope(body: dict, expected_code: str) -> dict:
    assert set(body.keys()) == {"error"}, body
    err = body["error"]
    assert {"code", "message", "request_id"}.issubset(err.keys()), err
    assert err["code"] == expected_code
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["request_id"], str) and err["request_id"]
    assert err["request_id"] != "-"
    return err


def test_events_malformed_body_returns_422_envelope(client):
    r = client.post(
        "/api/v1/sessions/events",
        json={"wrong": "shape"},
        headers={"X-Request-ID": "rid-422"},
    )
    assert r.status_code == 422
    err = _assert_envelope(r.json(), "VALIDATION_FAILED")
    assert err["request_id"] == "rid-422"
    assert r.headers["X-Request-ID"] == "rid-422"


def test_sessions_without_auth_returns_401_envelope(client):
    r = client.get("/api/v1/sessions", headers={"X-Request-ID": "rid-401"})
    assert r.status_code == 401
    err = _assert_envelope(r.json(), "AUTH_REQUIRED")
    assert err["request_id"] == "rid-401"


def test_cross_user_session_returns_404_not_403(client, mint_token, db_session):
    """AUTH-V0 §1(c): cross-user reads collapse to 404 (no 403 leak)."""
    # Insert a session owned by `alice`.
    db_session.add(SessionRow(id="s-alice-secret", user="alice"))
    db_session.commit()

    # Authenticate as `bob`.
    _, bob_headers = mint_token("bob")
    bob_headers["X-Request-ID"] = "rid-cross"
    r = client.get("/api/v1/sessions/s-alice-secret", headers=bob_headers)
    assert r.status_code == 404
    err = _assert_envelope(r.json(), "NOT_FOUND")
    assert err["message"] == "session not found"
    assert err["request_id"] == "rid-cross"


def test_unknown_session_id_returns_404_envelope(client, mint_token):
    _, headers = mint_token("alice")
    headers["X-Request-ID"] = "rid-missing"
    r = client.get(f"/api/v1/sessions/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404
    err = _assert_envelope(r.json(), "NOT_FOUND")
    assert err["request_id"] == "rid-missing"


def test_unhandled_exception_returns_500_envelope(client):
    r = client.get("/_test/boom", headers={"X-Request-ID": "rid-500"})
    assert r.status_code == 500
    err = _assert_envelope(r.json(), "INTERNAL")
    # Traceback is logged server-side, NEVER leaked to the body.
    assert "kaboom" not in err["message"]
    assert err["request_id"] == "rid-500"
    assert r.headers["X-Request-ID"] == "rid-500"
