"""Smoke test: structured JSON request log + X-Request-ID propagation."""
from __future__ import annotations

import io
import json
import logging
import os
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.mkdtemp(prefix="receipt-observability-")) / "test.db"
os.environ["RECEIPT_DB_URL"] = f"sqlite:///{_TMP_DB}"

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.core.logging import JsonFormatter  # noqa: E402
from apps.api.main import app  # noqa: E402


def _attach_capture_handler() -> tuple[logging.Handler, io.StringIO]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    return handler, buf


def test_request_emits_structured_log_with_required_fields():
    handler, buf = _attach_capture_handler()
    try:
        with TestClient(app) as client:
            r = client.get("/health", headers={"X-Request-ID": "test-rid-abc123"})
        assert r.status_code == 200
        assert r.headers["X-Request-ID"] == "test-rid-abc123"
    finally:
        logging.getLogger().removeHandler(handler)

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    records = [json.loads(ln) for ln in lines]
    req_logs = [
        r for r in records
        if r.get("logger") == "apps.api.request" and r.get("msg") == "http_request"
    ]
    assert req_logs, f"no request log emitted; saw: {records}"
    entry = next(r for r in req_logs if r.get("path") == "/health")

    for field in ("ts", "level", "msg", "request_id", "path", "method", "status", "duration_ms"):
        assert field in entry, f"missing {field} in {entry}"

    assert entry["request_id"] == "test-rid-abc123"
    assert entry["method"] == "GET"
    assert entry["status"] == 200
    assert isinstance(entry["duration_ms"], (int, float))
    assert entry["level"] == "INFO"


def test_request_without_inbound_header_generates_request_id():
    handler, buf = _attach_capture_handler()
    try:
        with TestClient(app) as client:
            r = client.get("/health")
        assert r.status_code == 200
        rid = r.headers["X-Request-ID"]
        assert rid and len(rid) >= 16
    finally:
        logging.getLogger().removeHandler(handler)

    records = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    req_log = next(
        r for r in records
        if r.get("logger") == "apps.api.request" and r.get("path") == "/health"
    )
    assert req_log["request_id"] == rid
