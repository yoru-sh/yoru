"""K8s-convention alias tests — /healthz and /readyz delegate to existing handlers.

Both paths must co-exist with /health and /health/ready (Dockerfile HEALTHCHECK and
Caddyfile smoke still hit /health; deploy.sh hits /healthz). These tests pin that
the aliases share behaviour with their canonical counterparts.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Match test_health.py: point Receipt DB at a tmp file BEFORE importing the app.
_TMP_DB = Path(tempfile.mkdtemp(prefix="receipt-ops-")) / "test.db"
os.environ["RECEIPT_DB_URL"] = f"sqlite:///{_TMP_DB}"

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402


def test_healthz_alias_returns_200():
    """`/healthz` mirrors `/health` — same status, same body."""
    with TestClient(app) as client:
        canonical = client.get("/health")
        alias = client.get("/healthz")
    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert alias.json() == canonical.json() == {"status": "ok"}


def test_readyz_alias_matches_ready(monkeypatch):
    """`/readyz` mirrors `/health/ready` — same status + `{"status":"ok"}` when DB up.

    Uses a file-backed sqlite engine (mirrors test_health_ready_depth.py fixture) so
    the 3-probe breakdown passes regardless of suite-order state. Without this, a
    prior test module that overwrites ops_router.engine or RECEIPT_DB_URL can leave
    the readiness probe in an unready state, which would falsely flag the alias.
    """
    import tempfile
    from pathlib import Path

    from sqlmodel import SQLModel, create_engine

    from apps.api.api.routers import ops_router as ops_router_module
    from apps.api.api.routers.receipt import models  # noqa: F401 — registers tables

    tmpdir = Path(tempfile.mkdtemp(prefix="receipt-ops-readyz-"))
    eng = create_engine(
        f"sqlite:///{tmpdir / 'test.db'}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(ops_router_module, "engine", eng)

    with TestClient(app) as client:
        canonical = client.get("/health/ready")
        alias = client.get("/readyz")
    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert alias.json()["status"] == canonical.json()["status"] == "ok"
