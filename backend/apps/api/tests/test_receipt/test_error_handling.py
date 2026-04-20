"""Error envelope + X-Request-ID propagation.

Canonical shape (wave-13 C3): every error response is
`{"error": {"code", "message", "request_id", "hint"}}` with matching
`X-Request-ID` response header. Covers four base cases:

  1. 500 Exception  → code=INTERNAL,            traceback logged never leaked
  2. 422 validation → code=VALIDATION_FAILED,   hint carries pydantic summary
  3. 404 HTTPException pass-through with request_id
  4. Inbound X-Request-ID is echoed (not regenerated)
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from apps.api.api.core.errors import install_error_handlers
from apps.api.core.request_logging import RequestLoggingMiddleware


class _Body(BaseModel):
    n: int


@pytest.fixture()
def error_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    install_error_handlers(app)

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    @app.get("/_test/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="not found")

    @app.post("/_test/validate")
    async def validate(body: _Body) -> dict:
        return {"ok": body.n}

    return app


def test_500_returns_envelope_and_request_id_header(error_app):
    with TestClient(error_app, raise_server_exceptions=False) as client:
        r = client.get("/_test/boom")
    assert r.status_code == 500
    assert r.headers.get("content-type", "").startswith("application/json")
    body = r.json()
    err = body["error"]
    assert err["code"] == "INTERNAL"
    assert err["message"] == "internal server error"
    assert "kaboom" not in err["message"]
    rid_header = r.headers.get("X-Request-ID")
    assert rid_header and len(rid_header) >= 16
    assert err["request_id"] == rid_header


def test_422_envelope_carries_validation_hint(error_app):
    with TestClient(error_app) as client:
        r = client.post("/_test/validate", json={"n": "not-an-int"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_FAILED"
    assert err["message"] == "request validation failed"
    assert err["hint"] and "n" in err["hint"]
    rid = r.headers.get("X-Request-ID")
    assert rid and err["request_id"] == rid


def test_404_http_exception_carries_detail_as_message(error_app):
    with TestClient(error_app) as client:
        r = client.get("/_test/missing")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "NOT_FOUND"
    assert err["message"] == "not found"
    rid = r.headers.get("X-Request-ID")
    assert rid and err["request_id"] == rid


def test_inbound_x_request_id_is_echoed_on_500(error_app):
    with TestClient(error_app, raise_server_exceptions=False) as client:
        r = client.get("/_test/boom", headers={"X-Request-ID": "trace-abc-xyz"})
    assert r.status_code == 500
    assert r.headers["X-Request-ID"] == "trace-abc-xyz"
    assert r.json()["error"]["request_id"] == "trace-abc-xyz"
