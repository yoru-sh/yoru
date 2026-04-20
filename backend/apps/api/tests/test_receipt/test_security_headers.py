"""SecurityHeadersMiddleware — wave-50 C3 coverage.

Confirms the 6-header bundle lands on every response regardless of method
or route. Mounts the middleware on a minimal app plus the real AuthRouter
so POST coverage exercises an actual mounted endpoint.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from apps.api.api.middleware.security_headers import SecurityHeadersMiddleware
from apps.api.api.routers.receipt.auth_router import AuthRouter
from apps.api.api.routers.receipt.db import get_session

_EXPECTED_HEADERS: dict[str, str] = {
    "strict-transport-security": "max-age=63072000; includeSubDomains; preload",
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "geolocation=(), microphone=(), camera=()",
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'"
    ),
}


@pytest.fixture()
def secured_app(engine) -> FastAPI:
    _app = FastAPI()
    _app.add_middleware(SecurityHeadersMiddleware)
    _app.include_router(AuthRouter().get_router(), prefix="/api/v1")

    @_app.get("/health")
    def _health() -> dict:
        return {"status": "ok"}

    def _override():
        with Session(engine) as s:
            yield s

    _app.dependency_overrides[get_session] = _override
    return _app


@pytest.fixture()
def secured_client(secured_app) -> TestClient:
    return TestClient(secured_app)


def _assert_all_six_headers(resp) -> None:
    for name, value in _EXPECTED_HEADERS.items():
        assert resp.headers.get(name) == value, (
            f"{name!r} expected {value!r} got {resp.headers.get(name)!r}"
        )


def test_all_six_headers_present_on_health(secured_client: TestClient) -> None:
    r = secured_client.get("/health")
    assert r.status_code == 200
    _assert_all_six_headers(r)


def test_headers_present_on_auth_endpoint(secured_client: TestClient) -> None:
    r = secured_client.post(
        "/api/v1/auth/hook-token",
        json={"user": "alice", "label": "laptop"},
    )
    assert r.status_code == 201
    _assert_all_six_headers(r)


def test_main_app_wires_security_headers_middleware() -> None:
    """Confirms the middleware is registered on the production app."""
    from apps.api.main import app

    assert any(
        m.cls is SecurityHeadersMiddleware for m in app.user_middleware
    ), "SecurityHeadersMiddleware not wired in apps.api.main"
