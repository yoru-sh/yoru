"""Request-metrics stub middleware tests.

Mounts a tiny FastAPI app behind RequestMetricsMiddleware (so the test is
independent of the receipt router stack and DB fixtures), hits a templated
route twice, and asserts /metrics exposes a counter line in Prometheus text
format with count >= 2.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from apps.api.api.middlewares.metrics import (
    RequestMetricsMiddleware,
    render_prometheus,
    reset,
)


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def get_item(item_id: str):
        return {"id": item_id}

    @app.get("/metrics")
    async def metrics_route() -> PlainTextResponse:
        return PlainTextResponse(
            content=render_prometheus(),
            media_type="text/plain; version=0.0.4",
        )

    app.add_middleware(RequestMetricsMiddleware)
    return app


def test_metrics_counter_uses_path_template_and_increments() -> None:
    reset()
    client = TestClient(_build_app())

    assert client.get("/items/abc").status_code == 200
    assert client.get("/items/xyz").status_code == 200

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text

    assert "# TYPE receipt_http_requests_total counter" in body

    # Path template kept as `/items/{item_id}` (NOT `/items/abc` or `/items/xyz`),
    # so the two concrete calls collapse into a single counter line.
    matching = [
        line
        for line in body.splitlines()
        if line.startswith("receipt_http_requests_total{")
        and 'method="GET"' in line
        and 'path="/items/{item_id}"' in line
        and 'status="200"' in line
    ]
    assert matching, f"no /items/{{item_id}} counter in body:\n{body}"
    count = int(matching[0].rsplit(" ", 1)[-1])
    assert count >= 2, f"expected counter >= 2, got {count}"

    # /metrics itself must be excluded from the counter map.
    assert 'path="/metrics"' not in body
