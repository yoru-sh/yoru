"""Smoke test: structured JSON request log + X-Request-ID propagation.

Targets the installed middleware chain — `StructuredLoggingMiddleware`
(`apps/api/api/middleware/structured_logging.py`) emits on logger
``receipt.http`` with the wave-40 C1 schema
`{timestamp, level, request_id, method, path, status, latency_ms, user_id}`
and carries the payload on the LogRecord via the `_receipt_http` extra key.
"""
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

from apps.api.api.middleware.structured_logging import (  # noqa: E402
    StructuredAccessLogFormatter,
)
from apps.api.main import app  # noqa: E402

_REQUEST_LOGGER_NAME = "receipt.http"


def _attach_capture_handler() -> tuple[logging.Handler, io.StringIO]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(StructuredAccessLogFormatter())
    handler.setLevel(logging.INFO)
    logging.getLogger(_REQUEST_LOGGER_NAME).addHandler(handler)
    return handler, buf


def _request_logs(buf: io.StringIO, path: str) -> list[dict]:
    records = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    return [r for r in records if r.get("path") == path]


def test_request_emits_structured_log_with_required_fields():
    with TestClient(app) as client:
        # Lifespan-startup re-runs `configure_structured_logger`, which clears
        # the `receipt.http` logger's handlers — attach AFTER lifespan.
        handler, buf = _attach_capture_handler()
        try:
            r = client.get("/health", headers={"X-Request-ID": "test-rid-abc123"})
        finally:
            logging.getLogger(_REQUEST_LOGGER_NAME).removeHandler(handler)
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "test-rid-abc123"

    entries = _request_logs(buf, "/health")
    assert entries, f"no request log emitted for /health; saw: {buf.getvalue()}"
    entry = entries[0]

    for field in (
        "timestamp",
        "level",
        "request_id",
        "method",
        "path",
        "status",
        "latency_ms",
        "user_id",
    ):
        assert field in entry, f"missing {field} in {entry}"

    assert entry["request_id"] == "test-rid-abc123"
    assert entry["method"] == "GET"
    assert entry["status"] == 200
    assert isinstance(entry["latency_ms"], int)
    assert entry["level"] == "info"


def test_request_without_inbound_header_generates_request_id():
    with TestClient(app) as client:
        handler, buf = _attach_capture_handler()
        try:
            r = client.get("/health")
        finally:
            logging.getLogger(_REQUEST_LOGGER_NAME).removeHandler(handler)
    assert r.status_code == 200
    rid = r.headers["X-Request-ID"]
    assert rid and len(rid) >= 16

    entries = _request_logs(buf, "/health")
    assert entries, f"no request log emitted for /health; saw: {buf.getvalue()}"
    assert entries[0]["request_id"] == rid
