"""MaxBodySizeMiddleware acceptance tests — wave-13 B4.

Covers:
    1. Oversized POST → 413 with the canonical error envelope.
    2. Within-cap POST to a guarded path → passes through to the app.
    3. GET (any size header) → middleware ignores non-POST methods.
    4. Non-guarded POST paths → pass through regardless of size.

The tests use a tiny cap (1024 bytes) so the pytest payloads stay realistic.
A stub FastAPI app is mounted behind the middleware + RequestLoggingMiddleware
+ the canonical error handlers so the envelope + X-Request-ID surface the same
way as production.
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.api.core.errors import install_error_handlers
from apps.api.core.max_body_size import MaxBodySizeMiddleware
from apps.api.core.request_logging import RequestLoggingMiddleware


def _build_app(max_bytes: int = 1024) -> FastAPI:
    """Stub app mirroring the ingest surface + /health probe."""
    app = FastAPI()

    @app.post("/api/v1/sessions/events", status_code=202)
    async def stub_ingest(payload: dict) -> dict:
        return {"accepted": len(payload.get("events", []))}

    @app.post("/api/v1/events", status_code=202)
    async def stub_events(payload: dict) -> dict:
        return {"ok": True}

    @app.post("/api/v1/ingest", status_code=202)
    async def stub_ingest_alias(payload: dict) -> dict:
        return {"ok": True}

    @app.get("/health")
    async def stub_health() -> dict:
        return {"status": "ok"}

    @app.post("/api/v1/sessions")
    async def stub_non_guarded(payload: dict) -> dict:
        return {"ok": True}

    # Order mirrors production wiring: MaxBodySize sits OUTSIDE the app and
    # INSIDE RequestLoggingMiddleware so `request_id` is already minted when
    # the 413 envelope is built. RequestLoggingMiddleware is added LAST so
    # Starlette wraps it OUTERMOST. The canonical error handlers are
    # registered so the envelope shape matches production.
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=max_bytes)
    app.add_middleware(RequestLoggingMiddleware)
    install_error_handlers(app)
    return app


def test_oversized_post_to_sessions_events_returns_413_envelope() -> None:
    """A 1 MB body MUST be rejected before the handler sees it."""
    client = TestClient(_build_app(max_bytes=1024))
    big_body = "x" * (1024 * 1024)  # 1 MB — far above the 1 KB test cap

    resp = client.post(
        "/api/v1/sessions/events",
        content=big_body,
        headers={
            "Content-Type": "application/json",
            "X-Request-ID": "rid-toobig",
        },
    )

    assert resp.status_code == 413, resp.text
    body = resp.json()
    assert set(body.keys()) == {"error"}, body
    err = body["error"]
    assert err["code"] == "PAYLOAD_TOO_LARGE"
    assert err["request_id"] == "rid-toobig"
    assert "exceeds" in err["message"]
    assert "/api/v1/sessions/events" in err["message"]
    # Canonical envelope carries `request_id` AND X-Request-ID header.
    assert resp.headers.get("X-Request-ID") == "rid-toobig"


def test_normal_5kb_batch_passes_through_to_handler() -> None:
    """A batch that fits the cap must reach the handler with 202."""
    # Use a larger cap so a realistic 5 KB batch is well within bounds.
    client = TestClient(_build_app(max_bytes=65536))
    events = [
        {"session_id": "s-1", "user": "u", "kind": "tool_use", "tool": "T", "content": "c" * 50}
        for _ in range(50)  # ~5 KB of JSON
    ]
    payload = {"events": events}
    body_size = len(json.dumps(payload).encode())
    assert 1024 < body_size < 65536, f"payload size {body_size} out of test band"

    resp = client.post("/api/v1/sessions/events", json=payload)

    assert resp.status_code == 202, resp.text
    assert resp.json() == {"accepted": 50}


def test_get_request_is_ignored_even_with_huge_content_length() -> None:
    """Middleware is POST-only — GETs must pass through regardless of size."""
    client = TestClient(_build_app(max_bytes=1024))
    # A GET with a declared Content-Length well over the cap. The middleware
    # must NOT 413 because method != POST.
    resp = client.get(
        "/health",
        headers={"Content-Length": "99999999"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}


def test_post_to_non_guarded_path_passes_through() -> None:
    """Non-ingest POST paths are out of scope — size cap does NOT apply."""
    client = TestClient(_build_app(max_bytes=1024))
    big_payload = {"blob": "z" * 4096}
    resp = client.post("/api/v1/sessions", json=big_payload)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}
