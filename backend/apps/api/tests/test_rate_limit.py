"""Token-bucket rate-limit middleware tests.

Mounts a stub `/api/v1/sessions/events` route behind RateLimitMiddleware so
the test exercises the middleware itself, independent of the receipt router
stack and DB fixtures.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.api.middlewares.rate_limit import RateLimitMiddleware


def _build_app(per_min: int = 60, burst: int = 30) -> FastAPI:
    app = FastAPI()

    @app.post("/api/v1/sessions/events")
    async def stub_ingest():
        return {"ok": True}

    @app.get("/api/v1/sessions")
    async def stub_list():
        return {"items": []}

    app.add_middleware(RateLimitMiddleware, per_min=per_min, burst=burst)
    return app


def test_burst_30_then_429_with_retry_after() -> None:
    client = TestClient(_build_app())
    for i in range(30):
        resp = client.post("/api/v1/sessions/events", json={"events": []})
        assert resp.status_code == 200, f"req {i + 1}: status={resp.status_code} body={resp.text}"
    # 31st request must be rate-limited.
    resp = client.post("/api/v1/sessions/events", json={"events": []})
    assert resp.status_code == 429, resp.text
    assert "retry-after" in {k.lower() for k in resp.headers.keys()}
    retry_after = int(resp.headers["Retry-After"])
    assert retry_after >= 1


def test_non_ingest_paths_are_not_limited() -> None:
    client = TestClient(_build_app(per_min=60, burst=2))
    # Far more than burst — list endpoint must keep returning 200.
    for _ in range(20):
        resp = client.get("/api/v1/sessions")
        assert resp.status_code == 200


def test_distinct_clients_have_independent_buckets() -> None:
    # Drain one bucket key, a different key still gets its full burst.
    mw = RateLimitMiddleware(app=None, per_min=60, burst=1)  # type: ignore[arg-type]
    now = 1000.0
    assert mw._consume("10.0.0.1", now) is None
    assert isinstance(mw._consume("10.0.0.1", now), int)  # 429
    assert mw._consume("10.0.0.2", now) is None  # different key, fresh bucket


def test_disabled_rate_returns_fallback_retry_after() -> None:
    mw = RateLimitMiddleware(app=None, per_min=0, burst=0)  # type: ignore[arg-type]
    retry_after = mw._consume("ip", 0.0)
    assert retry_after == 60
