"""Smoke tests for /health (liveness), /health/ready (readiness), /version."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Point Receipt DB at a tmp file BEFORE importing the app, so the engine
# (constructed at module-import time) and the lifespan's init_db() agree
# on a real, persistent SQLite path. :memory: would lose tables across
# pool connections without StaticPool wiring.
_TMP_DB = Path(tempfile.mkdtemp(prefix="receipt-health-")) / "test.db"
os.environ["RECEIPT_DB_URL"] = f"sqlite:///{_TMP_DB}"

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402


def test_health_liveness_is_200_and_body_ok():
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# /health/ready coverage: test_health_ready_depth.py (wave-13-C4 — 3-probe
# breakdown requires a real file-backed engine, not this module's :memory:).


def test_version_returns_version_and_python_keys():
    with TestClient(app) as client:
        r = client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body and body["version"]
    assert "python" in body and body["python"]
    py_runtime = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    assert body["python"] == py_runtime
    # git_sha is optional — present iff `git rev-parse` succeeds.
    if "git_sha" in body:
        assert body["git_sha"]
